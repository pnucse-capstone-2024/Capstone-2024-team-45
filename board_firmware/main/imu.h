#ifndef __IMU_H__
#define __IMU_H__

#define I2C_MASTER_SCL_IO           5                          /*!< GPIO number used for I2C master clock */ //(5)
#define I2C_MASTER_SDA_IO           4                          /*!< GPIO number used for I2C master data  */ //(4)
#define I2C_MASTER_NUM              0                          /*!< I2C master i2c port number, the number of i2c peripheral interfaces available will depend on the chip */
#define I2C_MASTER_FREQ_HZ          400000                     /*!< I2C master clock frequency */
#define I2C_MASTER_TX_BUF_DISABLE   0                          /*!< I2C master doesn't need buffer */
#define I2C_MASTER_RX_BUF_DISABLE   0                          /*!< I2C master doesn't need buffer */
#define I2C_MASTER_TIMEOUT_MS       1000

#define IMU_SENSOR_ADDR                 0x68        /*!< Slave address of the sensor */
#define IMU_WHO_AM_I_REG_ADDR           0x75        /*!< Register addresses of the "who am I" register */
#define IMU_PWR_MGMT_0_REG_ADDR         0x1F        /*!< Register addresses of the power managment register */

#define IMU_ACC_X_REG_ADDR              0x0B        /* Accelerometer, gyrometer data register address*/
#define IMU_ACC_Y_REG_ADDR              0x0D
#define IMU_ACC_Z_REG_ADDR              0x0F
#define IMU_GYRO_X_REG_ADDR             0x11
#define IMU_GYRO_Y_REG_ADDR             0x13
#define IMU_GYRO_Z_REG_ADDR             0x15


void getAccGyro(float* result);
void imu_init(void);
void imu_deinit(void);


#endif