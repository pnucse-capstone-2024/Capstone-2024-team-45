# 실행:
# cd GUI
# uvicorn main:app

# 서버관련 패키지
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# BLE, 비동기
import asyncio
from bleak import BleakClient, BleakScanner
import blecode as blecode

# 예외 traceback 용도로 사용
import traceback

# 서버생성, CROS관련 설정
app = FastAPI()
origins = [
	"*" # 모든 출처 허용
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    #allow_origin_regex="http://127\.0\.0\.1(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 클라이언트로부터 센서 정보 받을 때 사용할 구조
class DeviceInfo(BaseModel):
    dev_list : list
    pos : str
    time : int


# 예외처리 쉽게하려고 만듬
# 예외 발생할 만한 곳에 넣음
# 예외 발생시 정보를 클라이언트에게 넘김
def return_error(tag, e):
    traceback.print_exc()
    print("Except:\t", e)
    return {"type"      : "exception",
            "message"   : "("+tag+"):"+str(e)}

# 서버가 클라이언트에게 메시지 보낼 때(예외가 아닌 경우들)
def return_message(tag, msg):
    return {"type"      : "message",
            "message"   : "("+tag+"):"+msg}



# 이제부터 클라이언트 요청 처리하는 파트

# 루트
@app.get("/")
async def root():
    return {"type"      : "message",
            "message"   : "Usage: /devices(get), /scan(post), /predict_start(post), /predict_get(get)"}

# 장치 정보를 가져옴
@app.get("/devices")
async def devices():
    try:
        file = open("./devices.txt")
        devices_list = dict([dev.strip().split() for dev in file])
        devices_num = len(devices_list)
        file.close()

        return {"type"      : "data",
                "dev_num"   : devices_num,
                "dev_names" : list(devices_list.values()),
                "dev_addrs" : list(devices_list.keys()) }
            
    except Exception as e:
        return return_error("/devices", e)
    
# 장치 사용가능 여부 scan
@app.post("/scan")
async def scan(item : DeviceInfo):
    #print(item.dev_list)
    try:
        dev_online = await blecode.scan_device(item.dev_list)
        return {"type"      :"data",
                "dev_online": dev_online}
    
    except Exception as e:
        return return_error("/scan", e)

# 추론을 준비하고 실행함
@app.post("/predict_start")
async def predict_start(item : DeviceInfo):
    # 추론할 준비가 되어있지 않음...(이미 수행 중인 경우) 리턴
    if blecode.ble_status != "ready":
        return {"type"      :"message",
                "message"   :"아직 사용할 수 없음!"}
    try:
        await blecode.get_IMU(item.dev_list, item.time, item.pos)
        return {"type"      :"complete",
                "message"   :"자세 추론이 끝났습니다."}
    
    except Exception as e:
        return return_error("/predict_start", e)

# 추론 결과를 얻어옴 
@app.get("/predict_get")
async def predict_get():
    try:
        blestatus = blecode.ble_status
        print("ble status : ",blestatus)

        # ready 인 경우 -- 추론이 시작되지 않아 얻어갈 게 없음
        if blestatus == "ready":
            return return_message("/predict_get","predict_start이 시작되지 않았습니다.")
        # disconnected인 경우 -- 센서 연결 끊어짐 알림
        elif blestatus == "disconnected":
            return return_message("/predict_get","센서 연결이 끊어졌습니다.")
        # on 상태인 경우 -- 추론 결과 리턴
        elif blestatus == "on":
            return {"type"           :"data",
                    "predict_result" : blecode.predict_result}
        
        # wait 상태의 경우 -- 자세추론이 요청되었으나 준비하는 시간이 필요함
        # 클라이언트단과 타이밍을 맞추기 위해 상태가 변할 때까지 대기
        while(blecode.ble_status == "wait"):
            await asyncio.sleep(0.1)
        return {"type"      :"complete",
                "message"   :"wait_end"}
    
    except Exception as e:
        return return_error("/predict_get", e)

