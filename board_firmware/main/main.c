#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_nimble_hci.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "sdkconfig.h"
#include "esp_sleep.h"
#include "driver/gpio.h"
#include "imu.h"


/* 장치 이름 */
//#define CHECKER
#define DEVICE_NAME "ESPSensor_J"
#define DEV_ID 'J'

char *TAG = DEVICE_NAME;

/* BLE에 필요한 정보들 */
/* service, characteristic uuid(128bit)*/
#define SERVICE_UUID "\x45\xae\xf3\xee\xff\xc0\xb0\xba\xde\xaa\xa1\x87\x00\x00\xfe\xca"
#define CHARACTERISTIC_READ_UUID "\x45\xae\xf3\xee\xff\xc0\xb0\xba\xde\xaa\xa1\x87\x01\x00\xfe\xca"
#define CHARACTERISTIC_WRITE_UUID "\x45\xae\xf3\xee\xff\xc0\xb0\xba\xde\xaa\xa1\x87\x02\x00\xfe\xca"
#define CHARACTERISTIC_NOTIFY_UUID "\x45\xae\xf3\xee\xff\xc0\xb0\xba\xde\xaa\xa1\x87\x03\x00\xfe\xca"
uint8_t ble_addr_type;
void ble_app_advertise(void);

int ble_connected = 0;          // 게이트웨이와 연결 여부
int start_send = 0;             // 보내기 허용.

#define BLUE_GPIO 8             // 청색 LED gpio 번호
#define GREEN_GPIO 7             // 녹색 LED gpio 번호
#define BTN_GPIO 1              // 버튼 GPIO (저항 낮은 y). ADC연결 회피;;

#define SMPL_TIME_MS 50         // imu 데이터 갱신 기본 시간
uint16_t sampling_time_ms = SMPL_TIME_MS;

uint16_t conn_handle;
uint16_t attr_handle;

/* BLE로 전송할 데이터 */
/* 데이터의 순서와 실수 데이터(IMU)로 구성*/
struct imu_data_line{
    uint8_t id;
    uint32_t timestamp;
    float data[6];
} line;

/* 클라이언트에게 전송받을 데이터(값 조절)*/
typedef struct command_from_gateway{
    uint16_t type;
    uint16_t value;
} command;


/* 클라이언트 -> 서버(ESP)로 데이터 write 발생 시 실행*/
static int device_write(uint16_t conn_handle, uint16_t attr_handle, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    //printf("Data from the client: %.*s\n", ctxt->om->om_len, ctxt->om->om_data);
    if(ctxt->om->om_data == 0) return 0;
    command* cmd = (command*)(ctxt->om->om_data);
    if(cmd->type == 1){
        ESP_LOGI(TAG, "(gateway -> esp)sync(reset)");
        line.timestamp = 0;
        start_send = 1;
    }
    if(cmd->type == 2){
        ESP_LOGI(TAG, "(gateway -> esp)sampling rate change");
        sampling_time_ms = cmd->value;
        ESP_LOGI(TAG, "new sampling time(ms) : %d",sampling_time_ms);
    }
    if(cmd->type == 3){
        ESP_LOGI(TAG, "(gateway -> esp)start deep sleep");
        esp_deep_sleep_start();
    }
    return 0;
}

/* 서버 -> 클라이언트(Gateway)로 imu 데이터 전송. 클라이언트에서 읽기 요청시 실행됨 */
static int device_read(uint16_t con_handle, uint16_t attr_handle, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    //printf("request from client!!!\n");
    //os_mbuf_append(ctxt->om, imu_data_csv, strlen(imu_data_csv));
    //os_mbuf_append(ctxt->om, &imu_data, sizeof(imu_data));
    return 0;
}

/* notify용 callback... 호출되는지 확인불가...?*/
static int notifycallback(uint16_t conn_handle, uint16_t attr_handle, struct ble_gatt_access_ctxt *ctxt, void *arg){
    printf("...notify??");
    return 0;
}

// BLE GATT 서비스 정의
static const struct ble_gatt_svc_def gatt_svcs[] = {
    {.type = BLE_GATT_SVC_TYPE_PRIMARY,
     .uuid = BLE_UUID128_DECLARE(SERVICE_UUID),                 // Define UUID for device type
     .characteristics = (struct ble_gatt_chr_def[]){
         {.uuid = BLE_UUID128_DECLARE(CHARACTERISTIC_READ_UUID),           // Define UUID for reading
          .flags = BLE_GATT_CHR_F_READ,
          .access_cb = device_read},
         {.uuid = BLE_UUID128_DECLARE(CHARACTERISTIC_WRITE_UUID),           // Define UUID for writing
          .flags = BLE_GATT_CHR_F_WRITE,
          .access_cb = device_write},
         {.uuid = BLE_UUID128_DECLARE(CHARACTERISTIC_NOTIFY_UUID),          // Define UUID for notifying
          .flags = BLE_GATT_CHR_F_NOTIFY,
          .access_cb = notifycallback,
          .val_handle = &attr_handle},
         {0}}},
    {0}};

// GAP 이벤트 발생에 대한 핸들링
static int ble_gap_event(struct ble_gap_event *event, void *arg)
{
    switch (event->type)
    {
    // Advertise if connected
    case BLE_GAP_EVENT_CONNECT:
        ESP_LOGI("GAP", "BLE GAP EVENT CONNECT %s", event->connect.status == 0 ? "OK!" : "FAILED!");
        if (event->connect.status != 0)
        {
            ble_app_advertise();
        }
        else { // 연결 성공 시 상태 ON
            ble_connected = 1;
        }
        conn_handle = event->connect.conn_handle;
        break;
    // Advertise again after completion of the event
    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI("GAP", "BLE GAP EVENT DISCONNECTED");
        ble_app_advertise(); // 연결이 끊어진 경우, 다시 연결을 위해 Advertising 재시작
        ble_connected = 0;   // 상태 OFF
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        ESP_LOGI("GAP", "BLE GAP EVENT(adv complete)");
        ble_app_advertise();
        break;
    case BLE_GAP_EVENT_SUBSCRIBE: // notify 관련 이벤트 발생시.
        ESP_LOGI("GAP", "BLE GAP EVENT(Thank you for your subscribes)");
        ble_connected = 1; //데이터 받을수 있으므로 상태 ON
        break;
    default:
        break;
    }
    return 0;
}

// Define the BLE connection
void ble_app_advertise(void)
{
    // GAP - device name definition
    struct ble_hs_adv_fields fields;
    const char *device_name;
    memset(&fields, 0, sizeof(fields));
    device_name = ble_svc_gap_device_name(); // Read the BLE device name
    fields.name = (uint8_t *)device_name;
    fields.name_len = strlen(device_name);
    fields.name_is_complete = 1;
    ble_gap_adv_set_fields(&fields);

    // GAP - device connectivity definition
    struct ble_gap_adv_params adv_params;
    memset(&adv_params, 0, sizeof(adv_params));
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND; // connectable or non-connectable
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN; // discoverable or non-discoverable
    ble_gap_adv_start(ble_addr_type, NULL, BLE_HS_FOREVER, &adv_params, ble_gap_event, NULL);
}

// The application
void ble_app_on_sync(void)
{
    ble_hs_id_infer_auto(0, &ble_addr_type); // Determines the best address type automatically
    ble_app_advertise();                     // Define the BLE connection
}

// The infinite task
void host_task(void *param)
{
    nimble_port_run(); // This function will return only when nimble_port_stop() is executed
}

void app_main()
{
    /* BLE 초기설정 */
    nvs_flash_init();                          // 1 - Initialize NVS flash using
    // esp_nimble_hci_and_controller_init();   // 2 - Initialize ESP controller
    nimble_port_init();                        // 3 - Initialize the host stack
    ble_svc_gap_device_name_set(DEVICE_NAME);  // 4 - Initialize NimBLE configuration - server name
    ble_svc_gap_init();                        // 4 - Initialize NimBLE configuration - gap service
    ble_svc_gatt_init();                       // 4 - Initialize NimBLE configuration - gatt service
    ble_gatts_count_cfg(gatt_svcs);            // 4 - Initialize NimBLE configuration - config gatt services
    ble_gatts_add_svcs(gatt_svcs);             // 4 - Initialize NimBLE configuration - queues gatt services.
    ble_hs_cfg.sync_cb = ble_app_on_sync;      // 5 - Initialize application
    nimble_port_freertos_init(host_task);      // 6 - Run the thread

    /* LED GPIO 설정 */
    gpio_reset_pin(BLUE_GPIO);
    gpio_set_direction(BLUE_GPIO, GPIO_MODE_OUTPUT);

    #ifdef CHECKER
    /* LED GPIO 설정(버튼 눌림 확인용) */
    gpio_reset_pin(GREEN_GPIO);
    gpio_set_direction(GREEN_GPIO, GPIO_MODE_OUTPUT);
    /* 버튼 GPIO 설정*/
    gpio_reset_pin(BTN_GPIO);
    gpio_set_direction(BTN_GPIO, GPIO_MODE_INPUT);
    gpio_set_pull_mode(BTN_GPIO,GPIO_PULLUP_ONLY);
    /* 송신 데이터 필요없는부분 0으로*/
    line.data[0] = 0;
    line.data[1] = 0;
    line.data[2] = 0;
    line.data[3] = 0;
    line.data[4] = 0;
    line.data[5] = 0;
    #endif

    /* IMU 설정 */
    #ifndef CHECKER
    imu_init();
    #endif

    line.id = DEV_ID;

    /* loop */
    while(true){
        uint8_t blueled = 0;
        uint32_t sleep_time = 0;
        while(!ble_connected){
            /* 연결이 이루어지지 않아 Advertising하는 경우, 청색 LED를 계속 점멸*/
            gpio_set_level(BLUE_GPIO,blueled);
            blueled = !blueled;
            vTaskDelay(1000 / portTICK_PERIOD_MS);

            /* 계속 Advertising을 해도 연결되지 않은 경우, 전류 소모를 줄이기 위해 10분 후 deep sleep mode로 전환. */
            sleep_time += 1;    //1000ms(1초)마다 한 번씩 증가.
            if(sleep_time > 600){ //600초 후 deep sleep 모드로 전환. reset을 통해 깨어나야함.
                ESP_LOGI(TAG, "Good night");
                esp_deep_sleep_start();
            }
        }

        /* 연결 성공 시, 청색 LED 소등 */
        gpio_set_level(BLUE_GPIO, 0);

        while(ble_connected){
            /* IMU 데이터 수신 */
            #ifndef CHECKER
            getAccGyro(line.data);
            #endif

            #ifdef CHECKER
            if(gpio_get_level(1) == 0){
                //ESP_LOGI(TAG,"pressed...");
                line.data[0] = 1;
                gpio_set_level(GREEN_GPIO, 1);
            }
            else{
                line.data[0] = 0;
                gpio_set_level(GREEN_GPIO, 0);
            }
            #endif

            /* notify 수행.*/
            if(start_send){ //timestamp가 초기화된 이후부터 보내기
                ble_gatts_notify_custom(conn_handle,attr_handle,ble_hs_mbuf_from_flat(&line, sizeof(line)));
            }
            /* 시간정보 증가 */
            line.timestamp += sampling_time_ms;
            
            /* 정해진 시간만큼 delay*/
            vTaskDelay(sampling_time_ms / portTICK_PERIOD_MS);
        }

        /* 연결 해제될 시*/
        start_send = 0;
        #ifdef CHECKER
        gpio_set_level(GREEN_GPIO, 0); //불 끄기
        #endif
    }
    imu_deinit();
}


            /* imu_data_csv에 기록 */
            //sprintf(imu_data_csv,"%ld,%f,%f,%f,%f,%f,%f",timestamp++,imudata[0],imudata[1],imudata[2],imudata[3],imudata[4],imudata[5]);/789 