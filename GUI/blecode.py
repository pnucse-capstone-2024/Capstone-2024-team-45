# BLE 관련 코드들

# -------- 라이브러리 ----------#

# BLE, 비동기 프로그래밍 관련
import asyncio
from bleak import BleakClient, BleakScanner
# 데이터 처리
import struct
from collections import defaultdict
import numpy as np
import pickle 
# 머신러닝 추론
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
import tensorflow as tf

# -------- 변수들 ----------#

# 전역 상태변수
ble_status = "ready"      # ready(일반), wait(기다림), on(실행 중), disconnected(뭐가 연결 해제됨)
predict_result = "none"   # 추론 결과를 여기에다 기록

# BLE 서비스 characteristic uuid
UUID_NOTIFY = "cafe0003-87a1-aade-bab0-c0ffeef3ae45"  # 센서->게이트웨이
UUID_WRITE = "cafe0002-87a1-aade-bab0-c0ffeef3ae45"   # 게이트웨이->센서

# 같은 시간의 데이터를 한 행에 묶기 위한 변수들
frames = []                                 # 전체 데이터, 이후에 CSV파일로 저장. list(list) 형태
frames_temp = defaultdict(lambda:[])        # 임시로, 각 timestamp 별 센싱 데이터를 저장할 공간. 가득 차면 정렬하여 frames에 붙인다.
curr_frame_dev_num = defaultdict(lambda:0)  # frames_temp에서 timestamp 마다 센싱 데이터가 몇 개 쌓였는지 체크
max_frame_dev_num = 0                       # frames_temp의 timestamp마다 최대 몇 개의 데이터가 쌓일 수 있는지. 즉 데이터를 얻고 있는 총 센서 수를 뜻함.
sequence = np.array([])                     # 한 sequence(200개 frame)을 담기위한 변수

# Critical Section lock
lock = asyncio.Lock()

# 머신러닝 모델
modelstyle = "none"
model = None
scaler = None

# 센싱 속도 조절
timestep_num = 200  # 한 sequence에 몇개?(10초)
sampling_ms = 50   # 몇 ms 주기로 sampling?


# -------- 함수들 ----------#

# BLE 센서 스캔
async def scan_device(dev_list : list):
    print("센서 검색 중..")
    scanner = BleakScanner()

    # 장치 online여부 기록할 리스트
    dev_online = dict.fromkeys(dev_list,False)

    # 2초간 검색 시작
    await scanner.start()
    await asyncio.sleep(2.0)
    await scanner.stop()
    
    # 검색된 장치 가져오기
    devices = scanner.discovered_devices

    for d in devices:
        if d.address in dev_list:
            dev_online[d.address] = True
    
    return list(dev_online.values())
    

# 같은 시간의 데이터를 한 행에 묶기 위한 작업.
async def make_frame(data):
    # 장치 이름, 데이터 시간, 데이터로 분리
    devname = data[0].decode()
    devtime = data[1]
    devdata = data[2:]

    # 장치 이름과 데이터를 합치기
    temp = [devname]
    temp.extend(devdata)

    global frames
    global modelstyle
    global model
    global scaler
    global sequence
    global predict_result
    global timestep_num


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
            if modelstyle == "svm": #svm 사용하는 경우 sklearn 이용
                inp = np.array(frame[1:])
                res = model.predict(scaler.transform(inp.reshape(1,-1)))
                resstr = "True" if res[0]==1 else "False"
                print("{:.2f}s|".format(devtime/1000), resstr) #시간 데이터
                predict_result = resstr

            elif modelstyle == "lstm":
                inp = np.array(frame[1:])
                sequence = np.append(sequence, inp)
                if len(sequence) == len(inp) * timestep_num: # 한 sequence에 (200개의) 프레임이 다 모였다면...
                    print("{:.2f}s|".format(devtime/1000))                  
                    std = scaler.transform(sequence.reshape(-1,len(inp)))
                    res = model.predict(std.reshape(-1,timestep_num,len(inp)))
                    print(res)
                    resstr = "True" if res.argmax(axis=-1) == 1 else "False"
                    predict_result = resstr


                    sequence = np.array([]) # sequence 다시 비우기
                

            pass
            
    finally:
        # lock 해제
        lock.release()

# 센서로부터 값을 notify받을 때 발생하는 callback
async def when_notified(sender, data):

    # 수신된 값을 풀어해침.(c : char, i : int, 6f : float*6)
    imudata = struct.unpack('ci6f',data)

    # 서버 단에서 값을 보고 싶다면 주석 해제하기
    #print("\tName={}|Time={}|".format(imudata[0].decode(),imudata[1]));#,imudata[2:])

    # 수신된 값을 가지고 frame생성. (모든 센서 값이 한 행으로 이루어진 데이터)
    await make_frame(imudata)

# 센서와 연결 해제시 발생하는 callback
def on_disconnect(client: BleakClient):
    print("\t연결 해제됨:\tAddress={}".format(client.address))
    # 만약 값을 가져올 수 있는 상태에서 연결 해제가 발생한 경우
    # 무언가 연결 해제되었음을 알림
    global ble_status
    if ble_status == "on":
        ble_status = "disconnected"

# 센서에게 특정 메시지를 송신
async def write_message(client : BleakClient, time, message):
    print("\t메시지 전송!:","Address=",client.address)
    await client.write_gatt_char(UUID_WRITE, message) # 송신

# IMU 데이터 수집
async def get_IMU(dev_addrs : list, gettime : int, position : str):

    # 상태를 wait로--값을 받을 수 있을 때까지 대기 유도
    global ble_status
    ble_status = "wait"

    # 먼저 모델 불러오기
    global model
    global modelstyle
    global scaler
    model = None
    scaler = None
    modelstyle = "none"

    # 모델마다 필요한 sampling rate
    global sampling_ms
    global timestep_num
    sampling_ms = 50    #기본값
    timestep_num = 200

    # 운동자세마다 모델 경로, 파라미터 설정
    if position == "neck":
        modelstyle = "svm"
        modelpath = "./model/neck_2_m.pkl"
        scalerpath = "./model/neck_2_s.pkl"
    elif position == "shoulder":
        modelstyle = "lstm"
        modelpath = "./model/shoulder_m.h5"
        scalerpath = "./model/shoulder_s.pkl"
        sampling_ms = 100
        timestep_num = 100
    elif position == "hamstring":
        modelstyle = "lstm"
        modelpath = "./model/hamstringl_m.h5"
        scalerpath = "./model/hamstringl_s.pkl"
        sampling_ms = 100
        timestep_num = 100
    elif position == "bridge":
        modelstyle = "svm"
        modelpath = "./model/bridge_m.pkl"
        scalerpath = "./model/bridge_s.pkl"
    else:
        pass

    # sequence의 timestep개수와 sampling 주기 안 맞을 경우 Assert
    assert sampling_ms * timestep_num == 10000

    # 불러오기
    try:
        if modelstyle == "svm":
            file = open(modelpath, 'rb')
            model = pickle.load(file)
            file.close()
        elif modelstyle == "lstm":
            model = tf.keras.Sequential([
                tf.keras.layers.LSTM(units = 50, return_sequences = True, input_shape = (100,18)),
                tf.keras.layers.LSTM(units = 50),
                tf.keras.layers.Dropout(0.1),
                tf.keras.layers.Dense(50, activation = 'relu'),
                tf.keras.layers.Dense(2, activation = 'softmax')
            ])

            model.load_weights(modelpath)
            #model = tf.keras.models.load_model(modelpath)
        else:
            raise Exception("model style err")
        file = open(scalerpath, 'rb')
        scaler = pickle.load(file)
        file.close()
    except Exception as e:
        print("모델 파일을 불러오는 과정에서 문제 발생")
        raise e
    
    # 센싱 데이터 관리용 변수 초기화
    global frames
    global max_frame_dev_num
    global frames_temp
    global curr_frame_dev_num
    global sequence
    frames = []                                 # 전체 데이터 초기화
    frames_temp = defaultdict(lambda:[])        # 임시 데이터도 초기화.
    max_frame_dev_num = len(dev_addrs)            # 한 frame 당 최대 센서 개수 지정
    curr_frame_dev_num = defaultdict(lambda:0)  # 현재 timestamp 에서 센싱 완료한 센서 개수 초기화
    sequence = np.array([])
    

    print("센서와 연결 시작")
    
    # BleakClient 보관 리스트
    clients = list()   
    # 장치마다 client 클래스 생성
    for addr in dev_addrs:
        clients.append(BleakClient(addr, disconnected_callback=on_disconnect))
    
    try:
        # 장치 차례로 연결 시도
        for client in clients:
            await client.connect()
            print("\t센서 연결됨:\tAddress={}".format(client.address))
            await client.start_notify(UUID_NOTIFY,when_notified)
        
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

        # 여기서부터 측정 시작됨

        # 값 가져올수 있음
        ble_status = "on"

        # 정해진 시간만큼 측정을 위해 sleep
        await asyncio.sleep(gettime)
        
        # 시간 경과
        print("시간 경과")

        # stop notify
        for client in clients:    
            await client.stop_notify(UUID_NOTIFY)

        pass

    except Exception as e:
        print("센서 연결 과정에서 문제 발생")
        raise e

    finally:
        print('모든 센서 연결 해제')
        for client in clients:
            await client.disconnect()
        ble_status = "ready"
