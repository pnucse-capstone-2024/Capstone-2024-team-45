
#include <stdio.h>
#include "esp_log.h"
#include "driver/i2c.h"
#include "freertos/task.h"
#include "imu.h"

static const char *TAG = "IMU";

static esp_err_t imu_register_read(uint8_t reg_addr, uint8_t *data, size_t len)
{
    return i2c_master_write_read_device(I2C_MASTER_NUM, IMU_SENSOR_ADDR, &reg_addr, 1, data, len, I2C_MASTER_TIMEOUT_MS / portTICK_PERIOD_MS);
}

static esp_err_t imu_register_write_byte(uint8_t reg_addr, uint8_t data)
{
    int ret;
    uint8_t write_buf[2] = {reg_addr, data};

    ret = i2c_master_write_to_device(I2C_MASTER_NUM, IMU_SENSOR_ADDR, write_buf, sizeof(write_buf), I2C_MASTER_TIMEOUT_MS / portTICK_PERIOD_MS);

    return ret;
}

static esp_err_t i2c_master_init(void)
{
    int i2c_master_port = I2C_MASTER_NUM;

    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_MASTER_SDA_IO,
        .scl_io_num = I2C_MASTER_SCL_IO,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_MASTER_FREQ_HZ,
    };

    i2c_param_config(i2c_master_port, &conf);

    return i2c_driver_install(i2c_master_port, conf.mode, I2C_MASTER_RX_BUF_DISABLE, I2C_MASTER_TX_BUF_DISABLE, 0);
}

static int16_t endian_big_to_little_16(const int16_t data){
        return (data << 8) | ((data >> 8) & (uint16_t)255);
}

void getAccGyro(float* result){
    uint8_t data[2];
    /*Acc X*/
    ESP_ERROR_CHECK(imu_register_read(IMU_ACC_X_REG_ADDR, data, 2));
    result[0] = endian_big_to_little_16(*(int16_t*)data) / (float)2048;
    
    /*Acc Y*/
    ESP_ERROR_CHECK(imu_register_read(IMU_ACC_Y_REG_ADDR, data, 2));
    result[1] = endian_big_to_little_16(*(int16_t*)data) / (float)2048;
    
    /*Acc Z*/
    ESP_ERROR_CHECK(imu_register_read(IMU_ACC_Z_REG_ADDR, data, 2));
    result[2] = endian_big_to_little_16(*(int16_t*)data) / (float)2048;

    /*Gyro X*/
    ESP_ERROR_CHECK(imu_register_read(IMU_GYRO_X_REG_ADDR, data, 2));
    result[3] = endian_big_to_little_16(*(int16_t*)data) / 16.4;

    /*Gyro Y*/
    ESP_ERROR_CHECK(imu_register_read(IMU_GYRO_Y_REG_ADDR, data, 2));
    result[4] = endian_big_to_little_16(*(int16_t*)data) / 16.4;

    /*Gyro Z*/
    ESP_ERROR_CHECK(imu_register_read(IMU_GYRO_Z_REG_ADDR, data, 2));
    result[5] = endian_big_to_little_16(*(int16_t*)data) / 16.4;
}
void imu_init(void)
{
    uint8_t data[2];
    ESP_ERROR_CHECK(i2c_master_init());
    ESP_LOGI(TAG, "I2C initialized successfully");

    /* Read the WHO_AM_I register. ICM42670 : 0x67*/
    ESP_ERROR_CHECK(imu_register_read(IMU_WHO_AM_I_REG_ADDR, data, 1));
    ESP_LOGI(TAG, "WHO_AM_I = %X", data[0]);

    /* Config power mode */
    /* accelerometer, gyroscope Low Noise (LN) Mode*/
    ESP_ERROR_CHECK(imu_register_write_byte(IMU_PWR_MGMT_0_REG_ADDR, 0x1F));
    ESP_ERROR_CHECK(imu_register_read(IMU_PWR_MGMT_0_REG_ADDR, data, 1));
    ESP_LOGI(TAG, "Power mgmt0 = %X", data[0]);

    /*
    float imudata[6];     // Acc X, Acc Y, Acc Z, Gyro X, Gyro Y, Gyro Z

    while(1){
        getAccGyro(imudata);
        ESP_LOGI(TAG, "AccX:%f AccY:%f AccZ:%f", imudata[0], imudata[1], imudata[2]);
        ESP_LOGI(TAG, "GyroX:%f GyroY:%f GyroZ:%f\n", imudata[3], imudata[4], imudata[5]);
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }

    ESP_ERROR_CHECK(i2c_driver_delete(I2C_MASTER_NUM));
    ESP_LOGI(TAG, "I2C de-initialized successfully");*/
}

void imu_deinit(){
    ESP_ERROR_CHECK(i2c_driver_delete(I2C_MASTER_NUM));
    ESP_LOGI(TAG, "I2C de-initialized successfully");
}
