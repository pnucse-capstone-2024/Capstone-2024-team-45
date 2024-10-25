# BLE, 비동기 프로그래밍 관련
import asyncio
from bleak import BleakClient, BleakScanner
from bleak import exc
# 데이터 처리 관련
import pickle
import struct
import time
from datetime import datetime
from collections import defaultdict
import csv
import numpy as np
# 머신러닝 관련
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
import tensorflow as tf


# BLE 서비스 characteristic uuid
UUID_NOTIFY = "cafe0003-87a1-aade-bab0-c0ffeef3ae45"  # 센서로부터
UUID_WRITE = "cafe0002-87a1-aade-bab0-c0ffeef3ae45"   # 센서로

# notify 관련 상태 변수들.
notify_feedback = False     # notify callback 발생 시 센싱 값 즉각 확인할때 사용
notify_getdata = False      # 받고싶지 않은데 센싱값이 오는경우 무시할때 사용

# 센서 목록 변수들
device_list = dict()            # 모든 센서([주소] = 이름)
device_name_to_addr = dict()    # [이름] = 주소
device_num = 0                  # 검색된 장치 수
device_online = dict()          # 현재 Online인 센서

# 같은 시간의 데이터를 한 행에 묶기 위한 변수들
frames = []                                 # 전체 데이터, 이후에 CSV파일로 저장. list(list) 형태
frames_temp = defaultdict(lambda:[])        # 임시로, 각 timestamp 별 센싱 데이터를 저장할 공간. 가득 차면 정렬하여 frames에 붙인다.
curr_frame_dev_num = defaultdict(lambda:0)  # frames_temp에서 timestamp 마다 센싱 데이터가 몇 개 쌓였는지 체크
max_frame_dev_num = 0                       # frames_temp의 timestamp마다 최대 몇 개의 데이터가 쌓일 수 있는지. 즉 데이터를 얻고 있는 총 센서 수를 뜻함.
sequence = np.array([])                     # 한 sequence(200개 frame)을 담기위한 변수

# Critical Section 지킴이
lock = asyncio.Lock()

# 그냥 센싱할지/추론할지
do_predict = False

# 머신러닝 모델
modelstyle = "None"
model = None
scaler = None

# 센싱 속도 조절
timestep_num = 50  # 한 sequence(10초) 당 몇 개?
sampling_ms = 200  # 몇 ms 주기로?
assert (sampling_ms / 1000) * (timestep_num / 10) == 1

# ====================================================

# online 상태인 센서목록 출력
async def view_online():
    print("현재 센서 목록")
    for addr, online in device_online.items():
        print("\tName={}\tAddress={}\t{}".format(device_list[addr],addr, "ONLINE" if online else "offline"))

# BLE 센서 스캔
async def scan_device(printlist = True):
    print("센서 검색 중..")
    scanner = BleakScanner()
    
    # 기존 목록 초기화
    global device_online
    device_online = dict.fromkeys(device_list.keys(), False)

    # 2초간 검색 시작
    await scanner.start()
    await asyncio.sleep(2.0)
    await scanner.stop()
    
    # 검색된 장치 가져오기
    devices = scanner.discovered_devices

    for d in devices:
        if d.address in device_list.keys():
            device_online[d.address] = True
    
    # 검색 완료된 장치 목록 출력
    if printlist:
        await view_online()


# 센서와 연결 해제시 발생하는 callback
def on_disconnect(client):
    print("\t연결 해제됨:Name={}\tAddress={}".format(device_list[client.address],client.address))

# 같은 시간의 데이터를 한 행에 묶기 위한 작업.
async def make_frame(data):
    # 장치 이름, 데이터 시간, 데이터
    devname = data[0].decode()
    devtime = data[1]
    devdata = data[2:]

    # 장치 이름과 데이터를 합치기
    temp = [devname]
    temp.extend(devdata)

    global frames
    global model
    global modelstyle
    global scaler
    global sequence

    # Critical section lock
    await lock.acquire()
    try:
        frames_temp[devtime].append(temp)           # frames_temp 딕셔너리의 timestamp 위치에 장치 이름과 데이터 추가.
        curr_frame_dev_num[devtime] += 1            # 그리고 해당 timestamp의 센싱 데이터 수 1 증가

        if curr_frame_dev_num[devtime] == max_frame_dev_num: # 그러다 이 timestamp에서 모든 장치의 센싱이 완료되면
            # 이제 하나의 frame으로 구성해 frames에 append.
            frame = [devtime]                       # 먼저 가장 앞에 시간 데이터 추가
            for i in sorted(frames_temp[devtime], key=lambda x:x[0]): # 장치 이름순으로 정렬
                frame.extend(i[1:])                 # 장치 이름은 뗌
            
            # 최종적으로 frames에 추가
            frames.append(frame)

            # 머신러닝 추론 수행
            if do_predict:
                if modelstyle == "svm":
                    #print(frame)
                    inp = np.array(frame[1:])
                    res = model.predict(scaler.transform(inp.reshape(1,-1)))
                    #print(res)
                    print("{:.2f}s|".format(devtime/1000), end="")
                    print("True" if res[0]==1 else "False")
                elif modelstyle == "lstm":
                    inp = np.array(frame[1:])
                    sequence = np.append(sequence, inp) # 가장 앞은 ms임
                    if len(sequence) == len(inp) * timestep_num: #200개의 프레임이 모인다면...
                        print("now")
                        std = scaler.transform(sequence.reshape(-1,len(inp)))
                        res = model.predict(std.reshape(-1,timestep_num,len(inp)))
                        print(res)
                        print(res.argmax(axis=-1))

                        sequence = np.array([]) # 비우기

                    
            
    finally:
        # lock 해제
        lock.release()


# 센서로부터 값을 notify받을 때 발생하는 callback
async def when_notified(sender, data):

    # timestamp가 0이 되기 이전에 notify되는 값은 무시함.
    if notify_getdata == False:
        return
    
    # 수신된 값을 풀어해침.(c : char, i : int, 6f : float*6)
    imudata = struct.unpack('ci6f',data)

    if notify_feedback:  # 실시간으로 값 좀 보고 싶을 때
        #print("{:.3f}".format(time.time()),end="")
        print("\tName={}|Time={}|".format(imudata[0].decode(),imudata[1]),imudata[2:])

    # 수신된 값을 가지고 frame생성. (모든 센서 값이 한 행으로 이루어진 데이터)
    await make_frame(imudata)


# 센서에게 특정 메시지를 송신
async def write_message(client : BleakClient, time, message):
    await asyncio.sleep(time) # 일정시간 잠시 정지
    print("\t메시지 전송!:","Name=",device_list[client.address])
    await client.write_gatt_char(UUID_WRITE, message) # 수신
    # 참고) 송신할 메시지 구조 : hh (16bit 정수 2개)
    # 첫번째 정수 : 명령타입. (1:sync 맞추기(timestamp 초기화), 2:샘플링 속도 조절하기, 3:deep sleep)
    # 두번째 정수 : 값 (sync 맞추는 경우에는 따로 필요 없음)

# 센싱 데이터 저장.
async def save_result(filename : str, devices : list):
    # 최상단에 헤더 데이터 추가.
    head = "ax,ay,az,gx,gy,gz".split(",")  #a : accelerometer, g:gyroscope. x,y,z 세 축
    header=["ms"]  # timestamp. ms단위.
    for name in sorted(devices):
        for h in head:
            header.append(name + h)
    frames.insert(0,header)

    # frames를 csv파일의 형태로 저장함.
    with open(filename, "w", newline='') as file:
        writer = csv.writer(file)
        writer.writerows(frames)

# 문제가 발생했을 때..
def emer_save():
    # 최상단에 헤더 데이터 추가.
    head = "ax,ay,az,gx,gy,gz".split(",")  #a : accelerometer, g:gyroscope. x,y,z 세 축
    header=["ms"]  # timestamp. ms단위.
    dv = [d[0] for d in sorted(frames_temp[0], key=lambda x:x[0])]
    for name in dv:
        for h in head:
            header.append(name + h)
    frames.insert(0,header)

    # frames를 csv파일의 형태로 저장함.
    with open("tempfile.csv", "w", newline='') as file:
        writer = csv.writer(file)
        writer.writerows(frames)

# 센싱 중에 시간 알려줌.
async def time_indicate(maxtime :int):
    dt = 1
    for t in range(0,maxtime, dt):
        if not do_predict: print("진행 : {}/{} ({:.2f}%)".format(t,maxtime,100*t/maxtime))

        # 10초 단위로, 5초마다 올렸다 내렸다 지시하고 싶을때
        
        if t%10 == 0:
            print("올리세요")
        if t%10 == 5:
            print("내리세요")
        
        await asyncio.sleep(dt)

# IMU 데이터 수집
async def get_IMU(devices : list, gettime : int):
    print("센서와 연결 시작")    
    
    # BleakClient 보관 리스트
    clients = list()   
    
    # 장치마다 client 클래스 생성
    for name in devices:
        clients.append(BleakClient(device_name_to_addr[name], disconnected_callback=on_disconnect))
    
    try:
        # 장치 차례로 연결 시도(동시에 연결하게도 가능할 듯?)
        for client in clients:
            await client.connect()
            print("\t센서 연결됨:Name={}\tAddress={}".format(device_list[client.address],client.address))
            await client.start_notify(UUID_NOTIFY,when_notified)

        # 모든 센서의 time을 초기화하기 이전에 notified된 불필요한 데이터를
        # 수신하지 않다가, getdata flag를 True로 바꾸며 수신 시작
        global notify_getdata
        notify_getdata = True

        # 모든 장치의 센싱 속도를 조절(기존 20Hz)
        print("모든 센서의 sampling rate 초기화")
        task = []
        for client in clients:
            task.append(asyncio.create_task(write_message(client, 1, struct.pack("hh",2,sampling_ms))))
        await asyncio.wait(task)

        # 모든 장치의 timestamp를 동시에 초기화
        print("모든 센서의 timestamp 초기화")
        task = []
        for client in clients:
            task.append(asyncio.create_task(write_message(client, 1, struct.pack("hh",1,0))))
        await asyncio.wait(task)
        # 이를 통해 리스트에 등록된 모든 task가 동시에 수행된다.

        # 정해진 시간만큼 측정을 위해 sleep
        if(do_predict):
            print("{}초 동안 추론 중:".format(gettime))
        else:
            print("{}초 동안 측정 중:".format(gettime))

        await asyncio.gather(asyncio.sleep(gettime), time_indicate(gettime))
        #await asyncio.sleep(gettime)
        '''
        for t in range(0,gettime,10):
            await asyncio.sleep(5)
            print("5초")
            await asyncio.sleep(5)
            print("10초")'''

        print("시간 경과")

        # stop notify
        for client in clients:    
            await client.stop_notify(UUID_NOTIFY)

    except Exception as e:
        print("센서 연결 과정에서 문제 발생")
        print(e)

    finally:
        # notified 되는 값을 무시(callback에서)
        notify_getdata = False
        print('모든 센서 연결 해제')
        for client in clients:
            await client.disconnect()

async def sleep(address):
    try:
        sleepclient = BleakClient(address, disconnected_callback=on_disconnect)
        await sleepclient.connect()
        await write_message(sleepclient, 0, struct.pack("hh",3,0))

    except exc.BleakDeviceNotFoundError:
        # 이건 센서가 애초에 켜져있지 않은 경우
        pass

    except Exception as e:
        # 센서가 스스로 deep sleep에 빠져 정상적인 disconnect가 불가하다
        # 따라서 발생하는 exception을 흘릴 필요가 있음. (OSError)
        pass

# main function. 사용자에게 명령 입력받고 수행
async def run():
    global do_predict

    print("시작!")

    # 처음 장치 스캔
    await scan_device()

    while True:
        command = input(">>").strip()

        # 나가기
        if command == "quit":
            break
        
        # 센서 스캔하기
        elif command == "scan":
            await scan_device()

        # 현재 센서 목록 화인
        elif command == "list":
            await view_online()

        # IMU 센싱 값 받아오기
        elif command == "get":

            # 센싱 받고싶은 센서 입력
            print("IMU 데이터를 받을 센서 이름을 공백으로 구분하여 입력")
            inputstr = input("?>")
            if inputstr == "/all":
                devices = list(device_list.values())
            else:
                devices = inputstr.split()

            correct = True
            for d in devices:
                if d not in device_list.values():
                    print("에러!","이런 이름의 센서는 없음:",d)
                    correct = False
                elif device_online[device_name_to_addr[d]] == False:
                    print("에러!","현재 이 센서는 offline:",d)
                    correct = False
            if correct == False:
                continue

            # 센싱 시간 입력
            print("측정 시간을 입력(단위:초)")
            try:
                gettime = int(input("?>"))
            except ValueError:
                print("에러!","잘못된 값 형식")
                continue
            if gettime < 0:
                gettime = 0

            # notify 될 때 마다 데이터 확인 여부 결정
            print("데이터 수신 중 실시간 feedback? (y/N)")
            global notify_feedback
            notify_feedback = True if input("?>") == "y" else False

            # 센싱 데이터 관리용 변수 초기화
            global frames
            global max_frame_dev_num
            global frames_temp
            global curr_frame_dev_num
            frames = []                                 # 전체 데이터 초기화
            frames_temp = defaultdict(lambda:[])        # 임시 데이터도 초기화.
            max_frame_dev_num = len(devices)            # 한 frame 당 최대 센서 개수 지정
            curr_frame_dev_num = defaultdict(lambda:0)  # 현재 timestamp 에서 센싱 완료한 센서 개수 초기화

            # 센싱 수행
            do_predict = False
            await get_IMU(devices, gettime)
            
            # 센싱 수행 완료, 결과저장
            print('센싱 기록 결과 저장')
            timestr = datetime.today().strftime("%Y%m%d_%H%M%S")
            await save_result(timestr+"sensor.csv", devices)
            


        # 추론
        elif command == "predict":
            # 머신러닝을 통해 생성된 모델 불러오기

            global modelstyle
            global model
            global scaler
            global sequence

            #타입
            print("학습 모델 타입? (1:svm, 2:lstm)")
            modeltype = input("?>")
            if modeltype not in ["svm","lstm"]:
                print("잘못됨!")
                continue
            modelstyle = modeltype

            #모델
            print("불러올 모델의 파일 이름을 입력")
            modelname = input("?>")
            try:
                if modelstyle == "svm":
                    with open(modelname, 'rb') as file:
                        model = pickle.load(file)
                elif modelstyle == "lstm":
                    model = tf.keras.models.load_model(modelname)
            except Exception as e:
                print("모델을 불러오는 과정에서 문제가 발생했습니다.")
                print(e)
                continue
            
            # scaler
            print("불러올 모델 scaler의 파일 이름을 입력")
            modelscalername = input("?>")
            try:
                with open(modelscalername, 'rb') as file:
                    scaler = pickle.load(file)
            except Exception as e:
                print("모델 scaler를 불러오는 과정에서 문제가 발생했습니다.")
                print(e)
                continue

            sensor_num = len(scaler.mean_) // 6

            # 추론에 필요한 정확한 센서의 수 알림
            print("추론에 필요한 센서의 수 : ", sensor_num)

            # 센싱 받고싶은 센서 입력
            print("IMU 데이터를 받을 센서 이름을 공백으로 구분하여 입력")
            devices = input("?>").split()
            if len(devices) != sensor_num: # 센서의 수가 맞지 않은 경우
                print("에러!","필요한 센서 수가 맞지 않음")
                print("{}개 필요함, {}개 입력됨".format(sensor_num,len(devices)))
                continue

            # 센서가 존재하는지, ONLINE상태인지 검사
            correct = True
            for d in devices:
                if d not in device_list.values():
                    print("에러!","이런 이름의 센서는 없음:",d)
                    correct = False
                elif device_online[device_name_to_addr[d]] == False:
                    print("에러!","현재 이 센서는 offline:",d)
                    correct = False

            if correct == False:
                continue

            # 센싱 시간 입력
            print("측정 시간을 입력(단위:초)")
            try:
                gettime = int(input("?>"))
            except ValueError:
                print("에러!","잘못된 값 형식")
                continue
            if gettime < 0:
                gettime = 0

            # 센싱 데이터 관리용 변수 초기화
            frames = []                                 # 전체 데이터 초기화
            frames_temp = defaultdict(lambda:[])        # 임시 데이터도 초기화.
            max_frame_dev_num = len(devices)            # 한 frame 당 최대 센서 개수 지정
            curr_frame_dev_num = defaultdict(lambda:0)  # 현재 timestamp 에서 센싱 완료한 센서 개수 초기화
            sequence = np.array([]) # 추론시 사용하는 변수 초기화

            # 센싱&추론 수행
            do_predict = True
            await get_IMU(devices, gettime)

            #따로 데이터 저장은 수행하지 않음
        
        # deep sleep 모드로 센서 모드 변경
        elif command=="sleep":
            print("모든 Online 센서를 deep sleep 상태로 변경합니다.")
            # 먼저 online인 센서 감지
            await scan_device(printlist=False)

            # 동시에 sleep 메시지 전송
            task = []
            for addr, online in device_online.items():
                if not online: continue
                task.append(asyncio.create_task(sleep(addr)))
            await asyncio.wait(task)

            # 다시 장치 스캔하여 마무리
            await scan_device()

        else:
            # 없는 명령
            print("다시 입력해주세요..")


if __name__ == "__main__":
    # 센서 목록 받아오기
    with open("gateway/devices.txt",'r') as file:
        device_list = dict([dev.strip().split() for dev in file])
        device_name_to_addr = {v:k for k,v in device_list.items()}
        device_num = len(device_list)
        device_online = dict.fromkeys(device_list.keys(), False)
        #print(device_list)

    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run())

    except Exception as e: # 문제 생기는 경우
        print("비동기 loop exception")
        print(e)
        emer_save()
    finally:
        print("종료됨")
        #print(frames)
    