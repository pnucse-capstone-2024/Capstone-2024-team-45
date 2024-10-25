window.addEventListener("load", begin, false);


let dev_names = [];            // 전체 센서
let dev_addrs = [];            // 전체 센서 주소
let dev_names_to_addrs = {};   // 센서 이름:센서 주소 매칭
let dev_onlines = [];          // 전체 센서 상태
let dev_now_online = [];       // 현재 online 센서 이름

//let now_predict = false; //현재 predict가 이루어지고 있는지?
let predict_time = -1          // 측정할 시간

/* ----- Functions ----- */

// 장치 목록 불러오기
function get_device_information() {
    dev_names = [];
    dev_addrs = [];
    dev_names_to_addrs = {};

    let xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function () {
        if (this.readyState == 4 && this.status == 200) {
            received = JSON.parse(this.responseText);
            if (received.type == "data") {
                dev_names = received.dev_names;
                dev_addrs = received.dev_addrs;

                // 장치 목록 element 가져옴
                let dev_list = document.getElementById("dev_list");
                for (let i in dev_names) {
                    dev_names_to_addrs[dev_names[i]] = dev_addrs[i];

                    let div_dev = document.createElement("div");
                    div_dev.setAttribute("class", "dev");

                    let span_isonline = document.createElement("span");
                    span_isonline.setAttribute("class", "dev_isonline");

                    let span_addr = document.createElement("span");
                    span_addr.setAttribute("class", "dev_addr");
                    span_addr.appendChild(document.createTextNode(dev_addrs[i]));

                    let span_name = document.createElement("span");
                    span_name.setAttribute("class", "dev_name");
                    span_name.appendChild(document.createTextNode(dev_names[i]));

                    div_dev.appendChild(span_isonline);
                    div_dev.appendChild(span_name);
                    div_dev.appendChild(span_addr);

                    dev_list.appendChild(div_dev);
                }
            }
            else {
                add_alarm(received.type, received.message);
            }
        }
    }
    xhr.open("GET", "http://localhost:8000/devices", true);
    xhr.send();
}

// 장치 상태 스캔
function dev_scan() {
    add_alarm("message", "장치 상태를 불러옵니다");
    dev_now_online = [] // 기존 목록 초기화(필요한 변수)

    let xhr = new XMLHttpRequest()
    xhr.onreadystatechange = function () {
        if (this.readyState == 4 && this.status == 200) {
            received = JSON.parse(this.responseText)
            if (received.type == "data") { // 성공적
                add_alarm("complete", "장치 상태를 불러왔습니다.")
                dev_onlines = received.dev_online;

                // 장치 목록 element 가져옴
                let dev_list = document.getElementsByClassName("dev");
                // 상태 업데이트
                for (let i in dev_onlines) {
                    let onoff = dev_list[i].firstChild;
                    if (dev_onlines[i] == true) {
                        onoff.setAttribute("class", "dev_isonline on")
                        dev_now_online.push(dev_names[i])
                    }
                    else {
                        onoff.setAttribute("class", "dev_isonline")
                    }
                }
            }
            else { //실패
                add_alarm(received.type, received.message);
            }
        }
    }
    let senddata = {
        dev_list: dev_addrs,
        pos: "none",
        time: 0
    }
    xhr.open("POST", "http://localhost:8000/scan", true);
    xhr.setRequestHeader('Content-type', 'application/json');
    xhr.send(JSON.stringify(senddata));
}

//자세 추론
function dev_predict() {
    //시간이 정수가 아니면 리턴
    predict_time = parseInt(document.getElementById("inp_predicttime").value);
    if(predict_time == NaN){
        add_alarm("exception","정수의 시간을 입력해주세요.");
        return;
    }
    //0보다 작거나 같아도 리턴
    if(predict_time <= 0){
        add_alarm("exception","0 이상의 시간을 입력해주세요.");
        return;
    }

    // 선택한 자세 읽음
    let position = document.getElementById("sel_rehab").value;
    // 설명창 변경
    example_refresh();

    // 선택한 자세에 맞는 센서가 있는지 확인
    let not_online = []
    for (let s of position_essential_sensor[position]) {
        if (!dev_now_online.includes(s)) {
            not_online.push(s)
        }
    }
    if (not_online.length != 0) {
        document.getElementById("status_str").textContent = "필요한 센서를 모두 연결해주세요. 부족 : " + not_online.toString();
        return;
    }
    document.getElementById("status_str").textContent = "센서 연결 중...";
    // 결과창 보이게 설정
    document.getElementById("result").style.visibility = "visible";
    // 이제 시작버튼 block
    document.getElementById("btn_predict").disabled = true;

    // 필요한 센서들 주소 가져오기
    let connect_addrs = position_essential_sensor[position].map(function (e) {
        return dev_names_to_addrs[e];
    })

    // predict_start 호출
    // 서버측에서 추론 시작함
    let xhr = new XMLHttpRequest()
    xhr.onreadystatechange = function () {
        if (this.readyState == 4 && this.status == 200) {
            let received = JSON.parse(this.responseText);
            add_alarm(received.type, received.message)
        }
    }
    let senddata = {
        dev_list: connect_addrs,
        pos: position,
        time: predict_time
    }
    xhr.open("POST", "http://localhost:8000/predict_start", true);
    xhr.setRequestHeader('Content-type', 'application/json');
    xhr.send(JSON.stringify(senddata));

    // predict_get 호출
    // 서버측에서 추론 준비가 끝나면 wait_end라는 응답을 돌려줌
    let xhr2 = new XMLHttpRequest()
    xhr2.onreadystatechange = function () {
        if (this.readyState == 4 && this.status == 200) {
            let received = JSON.parse(this.responseText);
            // 추론 준비가 끝난 경우
            if (received.type == "complete" && received.message == "wait_end") {
                add_alarm("message", "자세 추론을 시작합니다.");
                document.getElementById("status_str").textContent = "센서 연결 끝";
                show_predict(position);
            }
            else {
                // 추론을 시작할 수 없는 경우..
                add_alarm(received.type, received.message);
                document.getElementById("btn_predict").disabled = false;

            }
        }
    }
    // predict_start 요청이 predict_get보다 늦어지는 경우가 있어,
    // predict_get 요청을 약간의 delay후 전송
    window.setTimeout(function(){
        xhr2.open("GET", "http://localhost:8000/predict_get", true);
        xhr2.send();
    }, 2000)
}

// 자세추론 중에 결과 확인하기
function show_predict(position) {
    let ellapsed = 0;       //시간 경과 확인
    let finalscore = 0;     //점수 기록용

    let result_time = document.getElementById("result_time");
    let result_time_bar = document.getElementById("result_time_graph_bar");
    let result_text = document.getElementById("result_text");
    result_text.textContent = "";
    let result_final = document.getElementById("result_final");
    result_final.textContent = "";

    let xhr = new XMLHttpRequest()
    xhr.onreadystatechange = function () {
        if (this.readyState == 4 && this.status == 200) {
            let received = JSON.parse(this.responseText);
            if (received.type == "data" && ellapsed <= predict_time) {
                //add_alarm(received.type, received.predict_result)
                // 흐른 시간을 계산하여 progress bar에 나타냄
                result_time.textContent = ellapsed.toFixed(1).toString() + "/" + predict_time.toString();
                result_time_bar.style.width = ((ellapsed % 10 + 0.5) * 10).toString() + "%"

                if (position_model_type["lstm"].includes(position)) { //반복동작
                    if (ellapsed % 10 == 0) { // 10초가 지날 때마다
                        //결과 표시
                        if (received.predict_result == "True") {
                            result_text.textContent += " ...O";
                            finalscore += 1;
                        }
                        else {
                            result_text.textContent += " ...X";
                        }
                    }
                }
                else {  //특정동작
                    if (received.predict_result == "True") {
                        finalscore += 1;
                        result_text.textContent = "목표 도달 O";
                    }
                    else {
                        result_text.textContent = "목표 도달 X";
                    }
                }
            }
            else if (ellapsed > predict_time) { //측정 시간 만료로 정지하는경우에 결과 표시
                window.clearInterval(timer);
                let resultstr = ""
                if (position_model_type["lstm"].includes(position)){
                    resultstr="반복동작" + finalscore.toString() + "회 성공!";
                }
                else{
                    let svmscore = (((finalscore/2)/predict_time)*100).toFixed(2)
                    resultstr="총 " + predict_time.toString() + "초 동안에 목표자세 총 "+ svmscore.toString() +"%만큼 달성!"
                }
                result_final.textContent = resultstr;
                document.getElementById("btn_predict").disabled = false;
                return;
            }
            else { //알 수 없는 이유로 정지함
                add_alarm(received.type, received.message)
                window.clearInterval(timer);
                result_final.textContent = "문제가 발생하여 자세 추론이 올바르게 이루어지지 못함.";
                document.getElementById("btn_predict").disabled = false;
                return;
            }
        }
    }

    //0.5초마다 요청을 보내 추론 결과를 갱신
    var timer = window.setInterval(function () {
        xhr.open("GET", "http://localhost:8000/predict_get", true);
        xhr.send();
        ellapsed += 0.5;
    }, 500)
}



//알람 추가하기
function add_alarm(msgtype, msg) {
    let alarm_list = document.getElementById("alarm_list");

    let div_alarm = document.createElement("div");
    if (msgtype == "exception") {
        div_alarm.setAttribute("class", "alarm exception");
    }
    else if (msgtype == "complete") {
        div_alarm.setAttribute("class", "alarm complete");
    }
    else {
        div_alarm.setAttribute("class", "alarm");
    }
    let btn_removealarm = document.createElement('button');
    btn_removealarm.setAttribute("class", "btn_removealarm");
    btn_removealarm.setAttribute("onclick", "remove_alarm(this)");
    btn_removealarm.appendChild(document.createTextNode("X"));

    let span_msg = document.createElement("span");
    span_msg.appendChild(document.createTextNode(msg));

    div_alarm.appendChild(btn_removealarm);
    div_alarm.appendChild(span_msg);

    alarm_list.appendChild(div_alarm);
}

/* ----- Event ----- */

// 버튼 이벤트
function remove_alarm(e) {
    //e는 버튼 오브젝트
    e.parentNode.remove()
}
function btn_scan() {
    dev_scan()
}
function btn_predict() {
    dev_predict()
}
function remove_alarm_all(e){
    // 알람 모두 제거하는 버튼
    let parent = e.parentElement;
    parent.replaceChildren();
    parent.appendChild(e)
}

function example_refresh() {
    // 선택한 자세 읽음
    let position = document.getElementById("sel_rehab").value;
    // 설명창 변경
    document.getElementById("show_example").style.visibility = "visible";
    document.getElementById("pos_title").textContent = position_title[position];
    document.getElementById("pos_description").innerHTML = position_description[position];
    document.getElementById("status_str").textContent = "";
    // 결과창 안 보이게 설정
    document.getElementById("result").style.visibility = "hidden";
}

// document 로드된 후에 시작
function begin() {
    //시작 시 먼저 장치 정보부터 받아오기.
    get_device_information();
}


//운동 관련 변수들
//const max_predict_time = 30;

// 추론모델마다 속한 운동들
const position_model_type = {
    "lstm": ["shoulder", "hamstring"],
    "svm": ["neck", "bridge"]
}
// 자세한 운동자세 명칭
const position_title = {
    "shoulder": "Assisted shoulder flexion",
    "hamstring": "Hamstring stretch",
    "neck": "Neck side extension",
    "bridge": "Bridge stretch"
};
// 운동자세 자세히
const position_description = {
    "shoulder":
    "0. 필요한 센서: C(왼손목) E(오른손목) F(배꼽) <br>\
    1. 양 손을 깍지끼고 양팔을 아래로 뻗습니다.<br>\
    2. 5초 동안 양 팔을 편 채 위로 올립니다.<br>\
    3. 다음 5초 동안 아래로 내립니다.<br>\
    4. 총 10회 반복합니다.<br>",

    "hamstring":
    "0. 필요한 센서: F(배꼽) G(무릎 위) H(발목 위) <br>\
    1. 의자에 앉아 허리를 곧게 폅니다. <br>\
    2. 5초간 왼쪽 종아리를 서서히 폅니다. <br>\
    3. 다음 5초간 왼쪽 종아리를 서서히 내립니다.<br>\
    4. 총 10회 반복합니다.<br>",

    "neck":
    "0. 필요한 센서: A, F <br>\
    1. 바른 자세를 유지합니다.<br>\
    2. 목에 힘을 풀고, 한 손을 들어 반대편 쪽의 머리를 잡고 당깁니다. <br>",

    "bridge":
    "0. 필요한 센서: A, B, C, D, E <br>\
    1. 바르게 누운 후 양쪽 무릎을 구부려 줍니다.<br>\
    2. 엉덩이를 들어 올리면서 허벅지에 힘을 줍니다. <br>\
    3. 다리와 배, 가슴이 평행이 되도록 합니다.<br>"
}
const position_essential_sensor =
{
    "shoulder": ["C", "E", "F"],
    "hamstring": ["F", "G", "H"],
    "neck": ["A", "F"],
    "bridge": ["A", "B", "C", "D", "E"]
};