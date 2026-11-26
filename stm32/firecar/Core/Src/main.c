/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "i2c.h"
#include "tim.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include <stdlib.h>   /* atoi */
#include <ctype.h>    /* toupper */
#include <math.h>     /* cosf, sinf, atan2f, sqrtf (오도메트리) */
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
/* PWM 최대값: CubeMX TIM1 Period(ARR)와 같은 값이어야 함 */
#define PWM_MAX        1599

/* 실제로 허용하는 PWM 최대값
 * 18650 3개 직렬(완충 12.6V)로 6V 모터를 돌리므로 6 / 12.6 ≈ 48% → 1599 × 0.48 ≈ 760
 * (AA 4개 6V로 돌릴 때는 PWM_MAX로 바꿔도 됨) */
#define PWM_LIMIT      760

/* ---- 하드웨어 채널 ↔ 차의 실제 좌우 연결 ----
 * 채널 A = PWMA·AIN1·AIN2(AO1/AO2) + TIM2 엔코더 → L1·L2 라벨 모터
 * 채널 B = PWMB·BIN1·BIN2(BO1/BO2) + TIM3 엔코더 → R1·R2 라벨 모터
 * 차를 뒤집어 조립하면서 실제 위치가 바뀜 (앞 = TB6612 쪽 기준):
 *   L1·L2 모터(채널 A)가 오른쪽, R1·R2 모터(채널 B)가 왼쪽 */
#define SWAP_LR        1      /* 1: 채널 A를 오른쪽, 채널 B를 왼쪽으로 사용 */

/* 채널에 + 명령을 줬을 때 차를 앞으로 밀면 1, 뒤로 밀면 -1 */
#define MOTOR_A_DIR    (1)    /* F 20에서 채널 A(오른쪽)는 앞으로 돌았음 */
#define MOTOR_B_DIR    (-1)   /* F 20에서 채널 B(왼쪽)는 뒤로 돌았음 → 뒤집기 */

/* 채널에 + 명령을 줬을 때 엔코더 카운트가 늘면 1, 줄면 -1 (모터 자체 기준, 위와 별개)
 * 지금까지 테스트에서 두 채널 모두 +명령 → 카운트 증가였음 */
#define ENC_A_DIR      (1)
#define ENC_B_DIR      (1)

/* ---- 속도 PI 제어 (TIM6 10ms마다 실행) ----
 * 속도 단위: 10ms 동안 늘어난 엔코더 카운트 (cnt/10ms)
 * 참고: 바퀴 띄우고 60%(PWM 960)일 때 약 37 cnt/10ms 나왔음 → 1 cnt/10ms ≈ PWM 26
 * KF: 목표 속도에 맞는 PWM을 미리 대충 넣어주는 값 (피드포워드)
 * KP: 지금 오차만큼 바로 보정
 * KI: 오차가 계속 남아 있으면 조금씩 쌓아서 보정 (뻑뻑한 쪽을 끝까지 따라잡게 함) */
#define KF             12.0f   /* 6V 때 22 → 전압 2배라 절반 정도로 */
#define KP             8.0f    /* 6V 때 15 */
#define KI             1.0f    /* 6V 때 2 */

/* ---- 명령 인터페이스 ----
 * 명령에 숫자를 안 붙이면 쓰는 기본 속도, 그리고 허용 최대 속도 [cnt/10ms]
 * (바퀴 띄우고 PWM 100%여도 대략 60 정도라 여유 있게 40으로 제한) */
#define CMD_DEFAULT_SPEED  20
#define CMD_MAX_SPEED      40
#define CMD_LINE_MAX       32     /* 명령 한 줄 최대 글자 수 */
#define RX_RING_SIZE       64     /* 수신 링버퍼 크기 (2의 거듭제곱) */

/* 안전장치: 마지막 명령 후 이 시간(ms) 동안 새 명령이 없으면 자동 정지
 * 지금은 손으로 명령 보내는 테스트라 2초, 라즈베리파이가 계속 보내게 되면 500 정도로 줄이기 */
#define CMD_TIMEOUT_MS     2000

/* HC-05 통신 속도: 평소(데이터 모드) 9600, AT 설정 모드는 38400으로 고정 */
#define BT_BAUD_DATA       9600
#define BT_BAUD_AT         38400

/* ---- I2C 센서 (I2C1: D15=SCL/PB8, D14=SDA/PB9) ----
 * HAL 함수에는 7비트 주소를 왼쪽으로 1칸 민 값(<<1)을 넘겨야 함 */
#define MPU_ADDR           (0x68 << 1)   /* MPU6050 (AD0 핀 비움 = 0x68) */
#define MPU_WHO_AM_I       0x75          /* 칩 확인용, 정품은 0x68을 돌려줌 */
#define MPU_PWR_MGMT_1     0x6B          /* 전원 켜면 잠든 상태 → 여기에 써서 깨움 */
#define MPU_CONFIG         0x1A          /* 디지털 저역통과필터(떨림 줄이기) */
#define MPU_GYRO_CONFIG    0x1B          /* 자이로 측정 범위 */
#define MPU_GYRO_ZOUT_H    0x47          /* 자이로 Z축 값 (상위 바이트, 다음 주소가 하위) */
#define GYRO_LSB_PER_DPS   65.5f         /* ±500°/s 범위일 때 1°/s = 65.5 */
#define IMU_PERIOD_MS      5             /* 자이로 읽는 주기 */
#define GYRO_CAL_SAMPLES   200           /* 시작할 때 영점 잡기용 샘플 수 (5ms × 200 = 1초) */
#define BOOT_WAIT_MS       5000          /* 전원 넣고 손 뗄 시간 (이 뒤에 영점을 잡음) */
#define IMU_STALE_MS       50            /* 자이로를 이 시간 넘게 못 읽으면 "각도 못 믿음" → 회전 중이면 즉시 정지 */
#define IMU_RECOVER_MS     200           /* I2C 복구 시도 간격 */

/* 자동 영점 보정: 바퀴가 멈춰 있고 회전이 이 값보다 작으면 "가만히 있는 중"으로 보고
 * 영점을 아주 조금씩(GYRO_BIAS_ALPHA 비율만큼) 지금 값 쪽으로 옮김 */
#define GYRO_STILL_DPS     3.0f
#define GYRO_BIAS_ALPHA    0.002f        /* 5ms마다 0.2%씩 → 약 2.5초에 걸쳐 따라감 */

/* 오래 멈춰 있을 때(바퀴가 STILL_LONG_MS 이상 완전히 정지)의 강한 보정
 * 바퀴가 안 도는데 차가 스스로 돌 수는 없으므로, 큰 오차(최대 STILL_LONG_DPS)도 영점 오차로 보고 빠르게 따라감
 * 이때는 각도도 더하지 않음(정지 중 각도 고정) → 영점이 틀어져 있어도 가만히 있는 동안 각도가 안 흘러감 */
#define STILL_LONG_MS      1000
#define STILL_LONG_DPS     20.0f
#define GYRO_BIAS_ALPHA_LONG 0.01f       /* 5ms마다 1%씩 → 약 0.5초에 따라감 */

/* 시작할 때 영점 잡기 검사: 1초 동안 값의 (최대-최소)가 이보다 크면 "움직였다"고 보고 다시 잡음 */
#define GYRO_CAL_MAX_SPREAD 100          /* 약 1.5°/s */
#define GYRO_CAL_RETRY      5

/* ---- 각도 회전 명령 T ---- */
#define TURN_TOL_DEG       2.0f          /* 목표와 이만큼 가까우면 도착으로 봄 */
#define TURN_KP            0.4f          /* 남은 각도 1°당 속도 0.4 → 남은 각도가 줄수록 느려짐 */
#define TURN_MIN_SPD       6             /* 이보다 느리면 바퀴가 출발을 못 함 */
#define TURN_MAX_SPD       18            /* 너무 빠르면 관성으로 멀리 지나침 */
#define TURN_TIMEOUT_MS    6000          /* 이 시간 안에 못 끝내면 멈춤 (바퀴가 걸렸을 때 대비) */

/* ---- 거리 이동 명령 D ---- */
#define CNT_PER_CM         170.0f        /* 1cm 이동 = 엔코더 약 170카운트 (F 15로 18cm 간 실측: 약 3065카운트) */
#define DRIVE_MAX_CM       500           /* 한 번에 갈 수 있는 최대 거리 */
#define DRIVE_TOL_CM       0.5f          /* 남은 거리가 이보다 작으면 도착 */
#define DRIVE_KP           1.0f          /* 남은 거리 1cm당 속도 1 → 마지막 20cm부터 서서히 느려짐 */
#define DRIVE_MIN_SPD      6
#define DRIVE_MAX_SPD      20
#define HEAD_KP            0.5f          /* 방향 오차 1°당 좌우 속도 차이 0.5 → 휘면 반대쪽으로 살짝 꺾어 직진 유지 */
#define HEAD_MAX_CORR      5             /* 방향 보정 최대값 (너무 세면 지그재그로 감) */

#define DEG2RAD            0.01745329f   /* π / 180 */

/* ---- 귀소 명령 G ---- */
#define HOME_TOL_CM        5.0f          /* 집까지 이만큼 가까우면 도착 */
#define HOME_MAX_TRIES     3             /* 회전+직진을 최대 몇 번 반복해서 다시 조준할지 */
#define RAD2DEG            57.2957795f   /* 180 / π */
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */
/* 엔코더 누적 카운트 (전원 켠 뒤부터 계속 더해짐)
 * 이제 TIM6 인터럽트에서만 갱신하므로 volatile */
static volatile int32_t enc_left_total  = 0;
static volatile int32_t enc_right_total = 0;
/* 직전에 읽은 타이머 카운터 값 (16비트) */
static uint16_t enc_left_prev  = 0;
static uint16_t enc_right_prev = 0;

/* PI 제어 변수 (인터럽트와 main이 같이 보므로 volatile) */
static volatile int target_l = 0, target_r = 0;   /* 목표 속도 [cnt/10ms] */
static volatile int speed_l  = 0, speed_r  = 0;   /* 측정 속도 [cnt/10ms] */
static volatile int pwm_l    = 0, pwm_r    = 0;   /* 출력 PWM (-1599 ~ 1599) */
static float integ_l = 0.0f, integ_r = 0.0f;      /* 오차 누적값 (I항) */

/* 명령을 받는 통로 하나(UART 하나)에 필요한 것들을 묶은 구조체
 * PC(USART2, USB)와 블루투스(USART1, HC-05) 두 개를 똑같은 코드로 처리하기 위해 */
typedef struct {
  UART_HandleTypeDef *huart;               /* 어느 UART인지 */
  uint8_t interactive;                     /* 1: 에코·프롬프트 출력(PC 터미널), 0: 안 함(폰 앱은 자기가 보여줌) */
  uint8_t rx_byte;                         /* HAL이 1글자 받아 넣는 자리 */
  volatile uint8_t ring[RX_RING_SIZE];     /* 받은 글자 저장소 (원형) */
  volatile uint16_t head;                  /* 인터럽트가 쓰는 위치 */
  uint16_t tail;                           /* 메인 루프가 읽는 위치 */
  char line[CMD_LINE_MAX];                 /* 조립 중인 명령 한 줄 */
  uint8_t len;
} cmd_port_t;

static cmd_port_t port_pc = { .huart = &huart2, .interactive = 1 };
static cmd_port_t port_bt = { .huart = &huart1, .interactive = 0 };

/* printf가 출력할 UART: 명령이 들어온 쪽으로 답하기 위해 잠깐씩 바꿔 씀 */
static UART_HandleTypeDef *out_uart = &huart2;

/* 타임아웃 안전장치용: 마지막으로 명령을 받은 시각과 통로 */
static uint32_t last_cmd_tick = 0;
static UART_HandleTypeDef *last_cmd_uart = &huart2;

/* IMU(MPU6050) 상태 */
static uint8_t  imu_ok = 0;          /* 1: MPU6050 초기화 성공 */
static float    gyro_bias_z = 0.0f;  /* 가만히 있을 때의 자이로 Z 값 (영점) */
static float    gyro_rate_z = 0.0f;  /* 현재 회전 속도 [°/s], 위에서 봤을 때 반시계(왼쪽)가 + */
static float    yaw_deg = 0.0f;      /* 누적 회전 각도 [°] */
static uint32_t imu_t_prev = 0;      /* 마지막으로 자이로를 읽은 시각 [ms] */
static uint32_t imu_last_ok = 0;     /* 마지막으로 읽기에 성공한 시각 [ms] */
static uint32_t still_since = 0;     /* 바퀴가 완전히 멈춘 시각 (0이면 움직이는 중) */
static uint32_t imu_err_count = 0;   /* 읽기 실패 횟수 (모터 잡음 등으로 I2C가 깨진 횟수) */
static uint32_t imu_recover_count = 0; /* I2C 버스 복구를 한 횟수 */
static uint32_t imu_recover_tick = 0;  /* 마지막 복구 시도 시각 */

/* T 명령(각도 회전) 상태 */
static uint8_t  turning = 0;         /* 1: 회전 중 */
static float    turn_target = 0.0f;  /* 도착해야 할 yaw [°] */
static int8_t   turn_dir = 0;        /* 처음 출발 방향: +1 왼쪽, -1 오른쪽 */
static uint32_t turn_t0 = 0;         /* 회전 시작 시각 */

/* D 명령(거리 이동) 상태 */
static uint8_t  driving = 0;         /* 1: 이동 중 */
static int8_t   drive_dir = 0;       /* +1 전진, -1 후진 */
static int32_t  drive_start = 0;     /* 출발할 때 좌우 엔코더 평균 */
static int32_t  drive_goal = 0;      /* 가야 할 카운트 (항상 양수) */
static float    drive_heading = 0.0f;/* 출발할 때 yaw = 유지할 방향 */
static uint32_t drive_t0 = 0;
static uint32_t drive_timeout = 0;   /* 거리에 따라 정해지는 제한 시간 [ms] */

/* 오도메트리: 출발점(집)을 (0,0), 그때 바라본 방향을 0°로 둔 좌표
 * x = 출발 방향으로 간 거리, y = 출발 방향 기준 왼쪽으로 간 거리 [cm] */
static float   pos_x = 0.0f;
static float   pos_y = 0.0f;
static int32_t odom_enc_prev = 0;    /* 지난번에 읽은 좌우 엔코더 평균 */

/* 각 동작의 결과 (귀소가 다음 단계로 넘어갈지 판단할 때 씀): 0 진행/없음, 1 성공, 2 실패 */
static uint8_t turn_result = 0;
static uint8_t drive_result = 0;

/* G 명령(귀소) 상태: 0 꺼짐, 1 집 방향으로 회전 중, 2 집으로 직진 중 */
static uint8_t homing = 0;
static uint8_t home_tries = 0;
static const char *home_result = "DONE";   /* 마지막 정렬 회전 뒤에 보낼 결과 문구 */

/* AT 중계 모드: 1이면 PC 터미널 ↔ HC-05를 그대로 이어줌 (HC-05 설정 확인·변경용) */
static uint8_t at_bridge = 0;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
void drive(int left, int right);
void drive_pwm(int left_pwm, int right_pwm);
void motor_stop(void);
void encoder_update(void);
void set_speed(int left, int right);
static void process_command(char *line);
static void at_bridge_enter(void);
static void print_status(void);
static void i2c_scan(void);
static void imu_init(void);
static void imu_update(void);
static void mpu_config(void);
static void i2c_bus_recover(void);
static void turn_start(int angle);
static void turn_update(void);
static void drive_start_cmd(int cm);
static void drive_update(void);
static void odom_reset(void);
static void odom_update(void);
static void home_leg(void);
static void homing_update(void);
static void home_face_start(const char *result);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
/* printf 출력을 out_uart로 보냄
 * 기본은 USART2(PC 터미널, 115200bps), 블루투스 명령에 답할 때는 USART1(HC-05, 9600bps) */
int _write(int file, char *ptr, int len)
{
  (void)file;
  HAL_UART_Transmit(out_uart, (uint8_t *)ptr, len, HAL_MAX_DELAY);
  return len;
}

/* 모터 한 쌍 제어: pwm = -PWM_MAX ~ +PWM_MAX
 * 양수면 IN1=HIGH, IN2=LOW (정방향), 음수면 반대 (역방향)
 * 크기(절댓값)가 PWM 듀티 → 속도 */
static void motor_set(uint32_t channel,
                      GPIO_TypeDef *in1_port, uint16_t in1_pin,
                      GPIO_TypeDef *in2_port, uint16_t in2_pin,
                      int pwm)
{
  if (pwm >  PWM_LIMIT) pwm =  PWM_LIMIT;   /* 모터 정격(6V) 보호 */
  if (pwm < -PWM_LIMIT) pwm = -PWM_LIMIT;

  if (pwm >= 0) {
    HAL_GPIO_WritePin(in1_port, in1_pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(in2_port, in2_pin, GPIO_PIN_RESET);
  } else {
    HAL_GPIO_WritePin(in1_port, in1_pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(in2_port, in2_pin, GPIO_PIN_SET);
    pwm = -pwm;
  }
  __HAL_TIM_SET_COMPARE(&htim1, channel, (uint32_t)pwm);
}

/* PWM 값으로 직접 구동 (PI 제어가 사용)
 * left/right는 "차의 실제 왼쪽/오른쪽", +는 "차를 앞으로" 기준
 * → SWAP_LR, MOTOR_x_DIR로 하드웨어 채널과 방향에 맞게 바꿔서 출력 */
void drive_pwm(int left_pwm, int right_pwm)
{
  int a = SWAP_LR ? right_pwm : left_pwm;   /* 채널 A에 줄 값 */
  int b = SWAP_LR ? left_pwm  : right_pwm;  /* 채널 B에 줄 값 */
  motor_set(TIM_CHANNEL_1, AIN1_GPIO_Port, AIN1_Pin, AIN2_GPIO_Port, AIN2_Pin, MOTOR_A_DIR * a);  /* L1 + L2 라벨 모터 */
  motor_set(TIM_CHANNEL_2, BIN1_GPIO_Port, BIN1_Pin, BIN2_GPIO_Port, BIN2_Pin, MOTOR_B_DIR * b);  /* R1 + R2 라벨 모터 */
}

/* 퍼센트로 구동: drive(60, 60) 전진, drive(-60, -60) 후진 (PI 없이 직접 돌릴 때) */
void drive(int left, int right)
{
  drive_pwm(PWM_MAX * left / 100, PWM_MAX * right / 100);
}

/* 정지: PWM 0, 방향 핀 모두 LOW */
void motor_stop(void)
{
  drive_pwm(0, 0);
  HAL_GPIO_WritePin(AIN1_GPIO_Port, AIN1_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(AIN2_GPIO_Port, AIN2_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(BIN1_GPIO_Port, BIN1_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(BIN2_GPIO_Port, BIN2_Pin, GPIO_PIN_RESET);
}

/* 엔코더 읽기: 16비트 카운터가 넘어가도(65535 → 0) 차이를 int16_t로 계산하면
 * 증가/감소량이 올바르게 나옴. 이제 TIM6 인터럽트에서 10ms마다 호출 */
void encoder_update(void)
{
  uint16_t now_a = (uint16_t)__HAL_TIM_GET_COUNTER(&htim2);   /* 채널 A 모터 엔코더 */
  uint16_t now_b = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);   /* 채널 B 모터 엔코더 */

  /* 각 채널의 증가량을 "차가 앞으로 가면 +" 기준으로 바꿈
   * (모터 방향을 뒤집은 채널은 엔코더도 같이 뒤집어야 PI가 반대로 폭주하지 않음) */
  int32_t d_a = ENC_A_DIR * MOTOR_A_DIR * (int16_t)(now_a - enc_left_prev);
  int32_t d_b = ENC_B_DIR * MOTOR_B_DIR * (int16_t)(now_b - enc_right_prev);

  /* 차의 실제 왼쪽/오른쪽에 더하기 */
  enc_left_total  += SWAP_LR ? d_b : d_a;
  enc_right_total += SWAP_LR ? d_a : d_b;

  enc_left_prev  = now_a;   /* 변수 이름과 달리 prev는 TIM2(A)/TIM3(B) 원래 값 저장용 */
  enc_right_prev = now_b;
}

/* 목표 속도 지정 [cnt/10ms]: set_speed(20, 20) 전진, set_speed(0, 0) 정지 */
void set_speed(int left, int right)
{
  target_l = left;
  target_r = right;
}

/* 바퀴 하나의 PI 계산 → PWM 반환 */
static int pi_calc(int target, int speed, float *integ)
{
  if (target == 0) {          /* 정지 명령이면 누적값도 비우고 PWM 0 */
    *integ = 0.0f;
    return 0;
  }

  float err = (float)(target - speed);
  *integ += err;

  /* 안티 와인드업: I항만으로 PWM_LIMIT를 넘지 않게 누적값 제한
   * (바퀴를 손으로 오래 잡고 있어도 누적값이 끝없이 커지지 않게) */
  float i_max = (float)PWM_LIMIT / KI;
  if (*integ >  i_max) *integ =  i_max;
  if (*integ < -i_max) *integ = -i_max;

  float out = KF * target + KP * err + KI * (*integ);
  if (out >  PWM_LIMIT) out =  PWM_LIMIT;
  if (out < -PWM_LIMIT) out = -PWM_LIMIT;
  return (int)out;
}

/* 10ms마다 실행: 속도 측정 → PI 계산 → PWM 출력 */
static void speed_control_step(void)
{
  int32_t prev_l = enc_left_total;
  int32_t prev_r = enc_right_total;
  encoder_update();
  speed_l = (int)(enc_left_total  - prev_l);
  speed_r = (int)(enc_right_total - prev_r);

  pwm_l = pi_calc(target_l, speed_l, &integ_l);
  pwm_r = pi_calc(target_r, speed_r, &integ_r);
  drive_pwm(pwm_l, pwm_r);
}

/* ---------------- I2C 센서 (MPU6050 자이로) ---------------- */

/* I2C 주소 1~127에 하나씩 "있어요?" 하고 물어봐서 대답한 주소를 출력
 * 0x68 = MPU6050, 0x0D = QMC5883L 나침반, 0x1E = HMC5883L 나침반 */
static void i2c_scan(void)
{
  int found = 0;
  printf("I2C scan:");
  for (uint16_t addr = 1; addr < 128; addr++) {
    if (HAL_I2C_IsDeviceReady(&hi2c1, addr << 1, 1, 2) == HAL_OK) {
      printf(" 0x%02X", addr);
      found++;
    }
  }
  printf(found ? "\r\n" : " none (check wiring)\r\n");
}

/* MPU6050 레지스터 1개 쓰기 */
static HAL_StatusTypeDef mpu_write(uint8_t reg, uint8_t val)
{
  return HAL_I2C_Mem_Write(&hi2c1, MPU_ADDR, reg, I2C_MEMADD_SIZE_8BIT, &val, 1, 10);
}

/* 자이로 Z축 원시값 읽기 (16비트, 부호 있음) */
static HAL_StatusTypeDef mpu_read_gz(int16_t *gz)
{
  uint8_t b[2];
  HAL_StatusTypeDef st = HAL_I2C_Mem_Read(&hi2c1, MPU_ADDR, MPU_GYRO_ZOUT_H, I2C_MEMADD_SIZE_8BIT, b, 2, 10);
  if (st == HAL_OK) *gz = (int16_t)((b[0] << 8) | b[1]);
  return st;
}

/* MPU6050 깨우기 + 필터·측정 범위 설정 (복구 후에도 다시 부름) */
static void mpu_config(void)
{
  mpu_write(MPU_PWR_MGMT_1, 0x01);   /* 잠 깨우기 + 자이로 X축 클럭을 기준으로 사용(더 안정적) */
  HAL_Delay(100);
  mpu_write(MPU_CONFIG, 0x03);       /* 저역통과필터 약 44Hz: 모터 진동 같은 빠른 떨림을 걸러냄 */
  mpu_write(MPU_GYRO_CONFIG, 0x08);  /* ±500°/s 범위: 제자리 회전도 넘치지 않을 만큼 넉넉함 */
  HAL_Delay(50);
}

/* I2C 버스 복구
 * 모터 잡음 때문에 통신 도중 신호가 깨지면, 센서가 SDA를 LOW로 붙잡은 채 멈추거나
 * STM32 I2C가 "바쁨(BUSY)" 상태에 갇혀서 그 뒤 읽기가 전부 실패함.
 * → I2C를 끄고, SCL을 손으로 9번 흔들어 센서가 하던 전송을 끝내게 한 뒤, STOP 신호를 만들고, I2C를 리셋·재시작 */
static void i2c_bus_recover(void)
{
  GPIO_InitTypeDef g = {0};

  HAL_I2C_DeInit(&hi2c1);                       /* I2C 끄기 (핀도 해제) */

  __HAL_RCC_GPIOB_CLK_ENABLE();
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8 | GPIO_PIN_9, GPIO_PIN_SET);
  g.Pin   = GPIO_PIN_8 | GPIO_PIN_9;            /* PB8 = SCL, PB9 = SDA 를 일반 출력(오픈 드레인)으로 */
  g.Mode  = GPIO_MODE_OUTPUT_OD;
  g.Pull  = GPIO_NOPULL;
  g.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &g);

  for (int i = 0; i < 9; i++) {                 /* SCL 클럭 9번 */
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET); HAL_Delay(1);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);   HAL_Delay(1);
  }
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_RESET); HAL_Delay(1);   /* STOP: SCL이 HIGH일 때 SDA LOW→HIGH */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);   HAL_Delay(1);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_SET);   HAL_Delay(1);

  __HAL_RCC_I2C1_FORCE_RESET();                 /* I2C 하드웨어 자체를 리셋 → 갇힌 BUSY 해제 */
  __HAL_RCC_I2C1_RELEASE_RESET();
  MX_I2C1_Init();                               /* CubeMX 설정 그대로 다시 켜기 (핀도 다시 I2C로) */
  imu_recover_count++;
}

/* MPU6050 깨우고 설정한 뒤, 1초 동안 가만히 있을 때 값을 평균 내서 영점 잡기
 * → 이 1초 동안 차를 건드리면 영점이 틀어져서 가만히 있어도 각도가 흘러감 */
static void imu_init(void)
{
  uint8_t who = 0;
  imu_ok = 0;

  if (HAL_I2C_Mem_Read(&hi2c1, MPU_ADDR, MPU_WHO_AM_I, I2C_MEMADD_SIZE_8BIT, &who, 1, 10) != HAL_OK) {
    printf("IMU: no answer at 0x68 (check SCL=D15, SDA=D14, 3.3V, GND)\r\n");
    return;
  }
  printf("IMU: WHO_AM_I = 0x%02X %s\r\n", who, (who == 0x68) ? "(MPU6050 OK)" : "(not 0x68: clone chip? continuing)");

  mpu_config();

  /* 1초 동안 평균을 내되, 그동안 값이 크게 흔들렸으면(=차가 움직였으면) 다시 잡음 */
  for (int tryno = 1; tryno <= GYRO_CAL_RETRY; tryno++) {
    printf("IMU: calibrating, keep the car still... (%d/%d)\r\n", tryno, GYRO_CAL_RETRY);
    int32_t sum = 0;
    int16_t gz, gmin = 32767, gmax = -32768;
    for (int i = 0; i < GYRO_CAL_SAMPLES; i++) {
      if (mpu_read_gz(&gz) != HAL_OK) { printf("IMU: read error\r\n"); return; }
      sum += gz;
      if (gz < gmin) gmin = gz;
      if (gz > gmax) gmax = gz;
      HAL_Delay(IMU_PERIOD_MS);
    }
    gyro_bias_z = (float)sum / GYRO_CAL_SAMPLES;
    if (gmax - gmin <= GYRO_CAL_MAX_SPREAD) break;      /* 충분히 가만히 있었음 → 확정 */
    printf("IMU: moved during calibration (spread=%d), retrying\r\n", gmax - gmin);
    if (tryno == GYRO_CAL_RETRY) printf("IMU: WARNING still moving, using last value (send I later)\r\n");
  }
  yaw_deg = 0.0f;
  imu_t_prev = HAL_GetTick();
  imu_last_ok = imu_t_prev;
  imu_ok = 1;
  printf("IMU: ready (bias=%d raw)\r\n", (int)gyro_bias_z);
}

/* 메인 루프에서 계속 호출: 5ms마다 자이로를 읽어 회전 속도 × 지난 시간을 각도에 더함
 * 각도 = Σ(각속도 × 시간). 지난 시간(dt)을 실제로 재서 곱하므로, 출력 때문에 주기가 조금 밀려도 맞게 쌓임 */
static void imu_update(void)
{
  if (!imu_ok) return;
  uint32_t now = HAL_GetTick();
  if (now - imu_t_prev < IMU_PERIOD_MS) return;

  int16_t gz;
  if (mpu_read_gz(&gz) != HAL_OK) {
    /* 읽기 실패: 각도를 더하지 않고, 실패가 계속되면 버스 복구 시도 */
    imu_err_count++;
    if (now - imu_last_ok > IMU_STALE_MS && now - imu_recover_tick > IMU_RECOVER_MS) {
      imu_recover_tick = now;
      i2c_bus_recover();
      mpu_config();
    }
    return;
  }

  float dt = (now - imu_t_prev) / 1000.0f;
  imu_t_prev = now;
  imu_last_ok = now;
  /* 실패로 한참 못 읽다가 다시 읽힌 경우, 그 사이 회전은 알 수 없으므로 더하지 않음
   * (지금 속도 × 긴 시간을 더하면 엉뚱한 값이 됨) */
  if (dt > (IMU_STALE_MS / 1000.0f)) return;

  gyro_rate_z = ((float)gz - gyro_bias_z) / GYRO_LSB_PER_DPS;

  /* 바퀴가 완전히 멈춰 있는지 (명령 0 + 엔코더 변화 0 + 동작 중 아님) */
  uint8_t wheels_still = (target_l == 0 && target_r == 0 && speed_l == 0 && speed_r == 0 &&
                          !turning && !driving && !homing);
  if (!wheels_still)        still_since = 0;
  else if (still_since == 0) still_since = now;
  uint8_t still_long = wheels_still && (now - still_since >= STILL_LONG_MS);
  float   a = (gyro_rate_z < 0) ? -gyro_rate_z : gyro_rate_z;

  if (still_long && a < STILL_LONG_DPS) {
    /* 1초 넘게 바퀴가 멈춰 있음 → 남은 회전값은 영점 오차
     * 각도는 더하지 않고(고정), 영점을 빠르게 지금 값 쪽으로 옮김 */
    gyro_bias_z += GYRO_BIAS_ALPHA_LONG * ((float)gz - gyro_bias_z);
    return;
  }

  yaw_deg += gyro_rate_z * dt;

  /* 막 멈춘 직후(1초 안)에는 작은 오차만 천천히 보정 (기존 방식) */
  if (wheels_still && a < GYRO_STILL_DPS) {
    gyro_bias_z += GYRO_BIAS_ALPHA * ((float)gz - gyro_bias_z);
  }
}

/* ---------------- T 명령: 자이로로 정확히 n도 돌기 ---------------- */

/* 회전 시작: 목표 yaw = 지금 yaw + angle (왼쪽 +, 오른쪽 -) */
static void turn_start(int angle)
{
  if (!imu_ok) { printf("ERR T: IMU not ready (send I)\r\n"); return; }
  if (angle == 0) { printf("OK T 0\r\n"); return; }
  turn_target = yaw_deg + (float)angle;
  turn_dir = (angle > 0) ? 1 : -1;
  turn_t0 = HAL_GetTick();
  turning = 1;
  turn_result = 0;
  printf("OK T %d\r\n", angle);
}

/* 메인 루프에서 계속 호출: 남은 각도에 비례해서 회전 속도를 정하고, 도착하면 멈춤
 * - 멀리 남았으면 빠르게, 가까워질수록 천천히 → 관성으로 지나치는 걸 줄임
 * - 목표를 지나쳤으면(남은 각도 부호가 바뀜) 되돌아가지 않고 바로 멈춤 → 왔다갔다 떨지 않음 */
static void turn_update(void)
{
  if (!turning) return;

  /* 자이로를 못 읽고 있으면 각도를 믿을 수 없으므로 바로 멈춤
   * (이걸 안 하면 각도가 멈춘 채로 목표에 영영 못 가서, 차가 계속 빙빙 돎) */
  if (HAL_GetTick() - imu_last_ok > IMU_STALE_MS) {
    set_speed(0, 0);
    turning = 0;
    out_uart = last_cmd_uart;
    printf("ERR T: IMU read failed (i2c err=%lu) - stopped\r\n", (unsigned long)imu_err_count);
    turn_result = 2;
    out_uart = &huart2;
    return;
  }

  float err = turn_target - yaw_deg;          /* 남은 각도, +면 아직 왼쪽으로 더 돌아야 함 */
  uint8_t passed = (turn_dir > 0) ? (err < 0) : (err > 0);
  uint8_t timeout = (HAL_GetTick() - turn_t0) > TURN_TIMEOUT_MS;

  if (passed || (err < TURN_TOL_DEG && err > -TURN_TOL_DEG) || timeout) {
    set_speed(0, 0);
    turning = 0;
    int y10 = (int)(yaw_deg * 10.0f);
    out_uart = last_cmd_uart;
    printf("%s T yaw=%s%d.%d deg\r\n", timeout ? "ERR timeout" : "DONE",
           y10 < 0 ? "-" : "", abs(y10) / 10, abs(y10) % 10);
    turn_result = timeout ? 2 : 1;
    out_uart = &huart2;
    return;
  }

  float a = (err > 0) ? err : -err;
  int spd = (int)(TURN_KP * a);
  if (spd < TURN_MIN_SPD) spd = TURN_MIN_SPD;
  if (spd > TURN_MAX_SPD) spd = TURN_MAX_SPD;

  if (err > 0) set_speed(-spd,  spd);   /* 왼쪽으로 돌기 */
  else         set_speed( spd, -spd);   /* 오른쪽으로 돌기 */

  last_cmd_tick = HAL_GetTick();         /* 회전 중에는 명령 타임아웃으로 멈추지 않게 (회전 자체 타임아웃이 있음) */
}

/* ---------------- D 명령: 엔코더로 정확히 n cm 가기 + 자이로로 직진 유지 ---------------- */

/* 좌우 엔코더 평균 = 차 중심이 간 거리 (카운트) */
static int32_t enc_avg(void)
{
  return (enc_left_total + enc_right_total) / 2;
}

static void drive_start_cmd(int cm)
{
  if (cm == 0) { printf("OK D 0\r\n"); return; }
  drive_dir     = (cm > 0) ? 1 : -1;
  drive_goal    = (int32_t)((cm > 0 ? cm : -cm) * CNT_PER_CM);
  drive_start   = enc_avg();
  drive_heading = yaw_deg;                      /* 지금 바라보는 방향을 그대로 유지 */
  drive_t0      = HAL_GetTick();
  /* 제한 시간: 기본 3초 + 1cm당 0.2초 (느린 속도로도 넉넉히 도착할 시간) */
  drive_timeout = 3000 + (uint32_t)(cm > 0 ? cm : -cm) * 200;
  driving = 1;
  drive_result = 0;
  printf("OK D %d\r\n", cm);
}

/* 메인 루프에서 계속 호출
 * 1) 남은 거리 = 목표 카운트 - 지금까지 간 카운트
 * 2) 속도 = 남은 거리에 비례 (가까워지면 느리게) → 정확히 멈춤
 * 3) 방향 보정: 출발 때 yaw와 지금 yaw 차이만큼 좌우 속도를 다르게 → 똑바로 감 */
static void drive_update(void)
{
  if (!driving) return;

  int32_t traveled = drive_dir * (enc_avg() - drive_start);   /* 가려는 방향으로 간 카운트 */
  int32_t remain   = drive_goal - traveled;
  float   remain_cm = remain / CNT_PER_CM;
  uint8_t timeout  = (HAL_GetTick() - drive_t0) > drive_timeout;

  if (remain_cm < DRIVE_TOL_CM || timeout) {   /* 도착 (지나친 경우 remain이 음수라 여기 포함) */
    set_speed(0, 0);
    driving = 0;
    int d10 = (int)(traveled * 10 / CNT_PER_CM);
    int y10 = (int)(yaw_deg * 10.0f);
    out_uart = last_cmd_uart;
    printf("%s D moved=%d.%d cm yaw=%s%d.%d deg\r\n", timeout ? "ERR timeout" : "DONE",
           d10 / 10, abs(d10 % 10), y10 < 0 ? "-" : "", abs(y10) / 10, abs(y10) % 10);
    drive_result = timeout ? 2 : 1;
    out_uart = &huart2;
    return;
  }

  int base = (int)(DRIVE_KP * remain_cm);
  if (base < DRIVE_MIN_SPD) base = DRIVE_MIN_SPD;
  if (base > DRIVE_MAX_SPD) base = DRIVE_MAX_SPD;

  /* 방향 보정: yaw가 줄었다(오른쪽으로 휨) → herr > 0 → 오른쪽 바퀴를 빠르게, 왼쪽을 느리게 → 왼쪽으로 돌아옴
   * 차가 도는 방향은 (오른쪽 속도 - 왼쪽 속도)로 정해지므로 전진/후진 모두 같은 식 */
  int corr = 0;
  if (imu_ok && (HAL_GetTick() - imu_last_ok) <= IMU_STALE_MS) {
    float herr = drive_heading - yaw_deg;
    corr = (int)(HEAD_KP * herr);
    if (corr >  HEAD_MAX_CORR) corr =  HEAD_MAX_CORR;
    if (corr < -HEAD_MAX_CORR) corr = -HEAD_MAX_CORR;
  }

  set_speed(drive_dir * base - corr, drive_dir * base + corr);
  last_cmd_tick = HAL_GetTick();      /* 이동 중에는 명령 타임아웃으로 멈추지 않게 (자체 제한 시간 있음) */
}

/* ---------------- 오도메트리: 엔코더 거리 + 자이로 방향으로 현재 위치 계산 ---------------- */

/* 지금 자리를 집(원점)으로 정함: 위치 0, 방향 0 */
static void odom_reset(void)
{
  pos_x = 0.0f;
  pos_y = 0.0f;
  yaw_deg = 0.0f;
  odom_enc_prev = enc_avg();
}

/* 메인 루프에서 계속 호출
 * 짧은 시간 동안 간 거리 d와 지금 방향 θ로 위치를 조금씩 더함
 *   x += d·cosθ,  y += d·sinθ
 * 아주 짧은 직선 조각들을 이어 붙이는 방식이라, 어떤 길로 돌아다녀도 지금 위치가 나옴
 * (제자리 회전은 좌우 엔코더가 반대로 움직여 평균 변화가 0 → 위치는 그대로, 방향만 바뀜) */
static void odom_update(void)
{
  int32_t now = enc_avg();
  int32_t d = now - odom_enc_prev;
  if (d == 0) return;
  odom_enc_prev = now;

  float d_cm = (float)d / CNT_PER_CM;
  float th = yaw_deg * DEG2RAD;
  pos_x += d_cm * cosf(th);
  pos_y += d_cm * sinf(th);
}

/* ---------------- G 명령: 집(O로 정한 자리)으로 돌아가기 ---------------- */

/* 귀소 끝: 결과를 명령 보낸 쪽으로 알림 */
static void home_finish(const char *result)
{
  homing = 0;
  set_speed(0, 0);
  UART_HandleTypeDef *prev_out = out_uart;
  out_uart = last_cmd_uart;
  printf("%s G pos x=%d y=%d cm (home dist %d cm) yaw=%d deg\r\n", result,
         (int)pos_x, (int)pos_y, (int)sqrtf(pos_x * pos_x + pos_y * pos_y), (int)yaw_deg);
  out_uart = prev_out;
}

/* 집에 도착한 뒤 마지막 단계: 출발할 때 바라보던 방향(yaw 0°)으로 돌아서기
 * → 급수대 앞에서 항상 같은 방향을 보고 서 있게 됨 (카메라 도킹·물 보충 정렬에 필요) */
static void home_face_start(const char *result)
{
  home_result = result;
  float angle = 0.0f - yaw_deg;
  while (angle >  180.0f) angle -= 360.0f;
  while (angle < -180.0f) angle += 360.0f;

  if (angle > 3.0f || angle < -3.0f) {
    UART_HandleTypeDef *prev_out = out_uart;
    out_uart = last_cmd_uart;
    printf("G face home direction: turn %d deg\r\n", (int)angle);
    turn_start((int)(angle > 0 ? angle + 0.5f : angle - 0.5f));
    out_uart = prev_out;
    homing = 3;
  } else {
    home_finish(result);
  }
}

/* 한 구간 시작: 지금 위치에서 집 방향을 계산해 그쪽으로 회전
 * - 집 방향 = atan2(-y, -x)  (지금 위치에서 원점을 가리키는 방향)
 * - 돌 각도 = 집 방향 - 지금 yaw 를 -180~180으로 맞춤 → 더 짧은 쪽으로 돎
 * 직진이 끝나면 다시 이 함수를 불러서 남은 오차를 한 번 더 조준 (최대 HOME_MAX_TRIES번) */
static void home_leg(void)
{
  float dist = sqrtf(pos_x * pos_x + pos_y * pos_y);
  if (dist < HOME_TOL_CM)          { home_face_start("DONE");               return; }
  if (home_tries >= HOME_MAX_TRIES) { home_face_start("DONE (best effort)"); return; }
  if (!imu_ok)                     { home_finish("ERR IMU not ready");  return; }
  home_tries++;

  float target = atan2f(-pos_y, -pos_x) * RAD2DEG;
  float angle  = target - yaw_deg;
  while (angle >  180.0f) angle -= 360.0f;
  while (angle < -180.0f) angle += 360.0f;

  UART_HandleTypeDef *prev_out = out_uart;   /* 명령 처리 중에 불릴 수도 있어서 원래 출력 대상을 기억 */
  out_uart = last_cmd_uart;
  printf("G leg %d: turn %d deg, then %d cm\r\n", home_tries, (int)angle, (int)(dist + 0.5f));
  if (angle > 3.0f || angle < -3.0f) {
    turn_start((int)(angle > 0 ? angle + 0.5f : angle - 0.5f));   /* 반올림 */
  } else {
    turn_result = 1;               /* 이미 거의 집 쪽을 보고 있으면 회전 생략 */
  }
  out_uart = prev_out;
  homing = 1;
}

/* 메인 루프에서 계속 호출: 회전이 끝나면 직진 시작, 직진이 끝나면 다음 구간 */
static void homing_update(void)
{
  if (!homing) return;

  if (homing == 1 && !turning) {
    if (turn_result == 2) { home_finish("ERR (turn failed)"); return; }
    float dist = sqrtf(pos_x * pos_x + pos_y * pos_y);   /* 회전 중 위치는 거의 안 변하지만 다시 계산 */
    int cm = (int)(dist + 0.5f);
    if (cm > DRIVE_MAX_CM) cm = DRIVE_MAX_CM;
    out_uart = last_cmd_uart;
    drive_start_cmd(cm);
    out_uart = &huart2;
    homing = 2;
  }
  else if (homing == 2 && !driving) {
    if (drive_result == 2) { home_finish("ERR (drive failed)"); return; }
    home_leg();                    /* 남은 오차가 있으면 다시 조준해서 한 번 더 */
  }
  else if (homing == 3 && !turning) {
    home_finish(turn_result == 2 ? "ERR (final turn failed)" : home_result);
  }
}

/* ---------------- 명령 인터페이스 ---------------- */

/* 사용법 출력 */
static void print_help(void)
{
  printf("\r\nCommands (speed: 0~%d cnt/10ms, default %d)\r\n", CMD_MAX_SPEED, CMD_DEFAULT_SPEED);
  printf("  F n : forward      B n : backward\r\n");
  printf("  L n : turn left    R n : turn right\r\n");
  printf("  S   : stop         ?   : status\r\n");
  printf("  O   : set home here (x=y=0, yaw=0)   (Z = same as O)\r\n");
  printf("  I   : I2C scan + IMU re-init (also sets home)\r\n");
  printf("  G   : go home (turn to home, drive straight, repeat up to %d times)\r\n", HOME_MAX_TRIES);
  printf("  T n : turn n deg in place (+ left, - right, e.g. T 90, T -90)\r\n");
  printf("  D n : drive n cm straight (+ forward, - backward, e.g. D 50, D -30)\r\n");
  printf("  ATMODE : HC-05 AT setting mode (PC terminal only)\r\n> ");
}

/* 현재 상태 한 줄 출력 */
static void print_status(void)
{
  printf("tgt L=%d R=%d | spd L=%d R=%d | pwm L=%d R=%d | enc L=%ld R=%ld\r\n",
         target_l, target_r, speed_l, speed_r, pwm_l, pwm_r,
         (long)enc_left_total, (long)enc_right_total);
  /* 실수 printf는 기본 설정에서 안 나오므로 0.1° 단위 정수로 출력 */
  int yaw10  = (int)(yaw_deg * 10.0f);
  int rate10 = (int)(gyro_rate_z * 10.0f);
  printf("imu %s | yaw=%s%d.%d deg | gz=%s%d.%d deg/s | i2c err=%lu recover=%lu last_ok=%lums ago\r\n",
         imu_ok ? "OK" : "NONE",
         yaw10 < 0 ? "-" : "", abs(yaw10) / 10, abs(yaw10) % 10,
         rate10 < 0 ? "-" : "", abs(rate10) / 10, abs(rate10) % 10,
         (unsigned long)imu_err_count, (unsigned long)imu_recover_count,
         (unsigned long)(HAL_GetTick() - imu_last_ok));
  /* 집까지 거리와 집이 있는 방향 (G 명령이 쓸 값) */
  float home_dist = sqrtf(pos_x * pos_x + pos_y * pos_y);
  float home_dir  = atan2f(-pos_y, -pos_x) * RAD2DEG;
  printf("pos x=%d y=%d cm | home %d cm, direction %d deg\r\n",
         (int)pos_x, (int)pos_y, (int)home_dist, (int)home_dir);
}

/* 대소문자 무시하고 두 문자열이 같은지 */
static int str_eq_nocase(const char *a, const char *b)
{
  while (*a && *b) {
    if (toupper((unsigned char)*a) != toupper((unsigned char)*b)) return 0;
    a++; b++;
  }
  return (*a == '\0' && *b == '\0');
}

/* 명령 한 줄 해석·실행. 예: "F 20", "r15", "s", "?" */
static void process_command(char *line)
{
  while (*line == ' ') line++;              /* 앞 공백 건너뛰기 */
  if (*line == '\0') return;                /* 빈 줄은 무시 */

  /* ATMODE: 한 글자 명령보다 먼저 검사 (안 그러면 'A'로 시작하는 다른 명령처럼 해석됨)
   * HC-05 자신을 설정하는 모드라 PC 터미널에서만 허용 */
  if (str_eq_nocase(line, "ATMODE")) {
    if (out_uart == &huart2) at_bridge_enter();
    else printf("ERR ATMODE: PC only\r\n");
    return;
  }

  /* 무슨 명령이든 들어왔다 = 아직 연결이 살아 있다 → 타임아웃 시계 다시 시작 */
  last_cmd_tick = HAL_GetTick();
  last_cmd_uart = out_uart;

  char cmd = (char)toupper((unsigned char)line[0]);

  /* 회전 중에 다른 명령(상태 조회 ? 제외)이 오면 회전 취소 → 그 명령이 우선 */
  if (cmd != '?') { turning = 0; driving = 0; homing = 0; }

  /* T: 각도는 음수(오른쪽)도 있고 범위도 속도와 달라서 따로 처리 */
  if (cmd == 'T') {
    char *p = line + 1;
    while (*p == ' ') p++;
    if (!(isdigit((unsigned char)*p) || ((*p == '-' || *p == '+') && isdigit((unsigned char)p[1])))) {
      printf("ERR T needs angle (e.g. T 90, T -90)\r\n");
      return;
    }
    int ang = atoi(p);
    if (ang > 360 || ang < -360) { printf("ERR T range -360~360\r\n"); return; }
    turn_start(ang);
    return;
  }

  /* D: 거리(cm), 음수는 후진 */
  if (cmd == 'D') {
    char *p = line + 1;
    while (*p == ' ') p++;
    if (!(isdigit((unsigned char)*p) || ((*p == '-' || *p == '+') && isdigit((unsigned char)p[1])))) {
      printf("ERR D needs cm (e.g. D 50, D -30)\r\n");
      return;
    }
    int cm = atoi(p);
    if (cm > DRIVE_MAX_CM || cm < -DRIVE_MAX_CM) { printf("ERR D range -%d~%d\r\n", DRIVE_MAX_CM, DRIVE_MAX_CM); return; }
    drive_start_cmd(cm);
    return;
  }

  /* 숫자 부분: 없으면 기본 속도 */
  int v = CMD_DEFAULT_SPEED;
  char *num = line + 1;
  while (*num == ' ') num++;
  if (*num != '\0') {
    if (!isdigit((unsigned char)*num)) { printf("ERR bad number\r\n"); return; }
    v = atoi(num);
  }
  if (v > CMD_MAX_SPEED) { printf("ERR max %d\r\n", CMD_MAX_SPEED); return; }

  switch (cmd) {
    case 'F': set_speed( v,  v); printf("OK F %d\r\n", v); break;
    case 'B': set_speed(-v, -v); printf("OK B %d\r\n", v); break;
    case 'L': set_speed(-v,  v); printf("OK L %d\r\n", v); break;   /* 왼쪽 뒤로, 오른쪽 앞으로 */
    case 'R': set_speed( v, -v); printf("OK R %d\r\n", v); break;   /* 왼쪽 앞으로, 오른쪽 뒤로 */
    case 'S': set_speed( 0,  0); printf("OK S\r\n");        break;
    case '?': print_status();                                  break;
    case 'H': print_help();                                    return;
    case 'G': home_tries = 0; printf("OK G (going home)\r\n"); home_leg(); break;
    case 'O':
    case 'Z': odom_reset(); printf("OK O (home set here)\r\n"); break;
    case 'I': imu_err_count = 0; imu_recover_count = 0;
              i2c_scan(); imu_init(); odom_reset();
              printf("home set here\r\n");                  break;
    default:  printf("ERR unknown '%c' (H: help)\r\n", line[0]); break;
  }
}

/* 한 통로의 링버퍼에서 글자를 꺼내 한 줄로 모으고, Enter가 오면 실행
 * 답장은 그 명령이 들어온 통로로 보냄 */
static void port_poll(cmd_port_t *p)
{
  out_uart = p->huart;
  while (p->tail != p->head) {
    char c = (char)p->ring[p->tail & (RX_RING_SIZE - 1)];
    p->tail++;

    if (c == '\r' || c == '\n') {            /* Enter: 한 줄 완성 (CR+LF면 두 번째는 빈 줄이라 무시됨) */
      if (p->len > 0) {
        if (p->interactive) printf("\r\n");
        p->line[p->len] = '\0';
        process_command(p->line);
        p->len = 0;
        if (p->interactive) printf("> ");
      }
    } else if (c == '\b' || c == 0x7F) {      /* 백스페이스: 한 글자 지우기 */
      if (p->len > 0) {
        p->len--;
        if (p->interactive) printf("\b \b");
      }
    } else if (p->len < CMD_LINE_MAX - 1) {
      p->line[p->len++] = c;
      if (p->interactive) HAL_UART_Transmit(p->huart, (uint8_t *)&c, 1, HAL_MAX_DELAY);  /* 에코 */
    }
  }
  out_uart = &huart2;
}

/* 두 통로 모두 확인 */
static void uart_poll_commands(void)
{
  port_poll(&port_pc);
  port_poll(&port_bt);
}

/* 안전장치: 움직이는 중인데 CMD_TIMEOUT_MS 동안 명령이 없으면 정지 */
static void check_cmd_timeout(void)
{
  if ((target_l != 0 || target_r != 0) &&
      (HAL_GetTick() - last_cmd_tick > CMD_TIMEOUT_MS)) {
    set_speed(0, 0);
    out_uart = last_cmd_uart;
    printf("STOP (timeout)\r\n");
    out_uart = &huart2;
  }
}

/* ---------------- HC-05 AT 중계 모드 ---------------- */

/* HC-05 쪽 UART(USART1) 속도를 바꿈: 받던 걸 멈추고 → 새 속도로 다시 설정 → 다시 받기 시작 */
static void bt_set_baud(uint32_t baud)
{
  HAL_UART_AbortReceive_IT(&huart1);
  huart1.Init.BaudRate = baud;
  if (HAL_UART_Init(&huart1) != HAL_OK) Error_Handler();
  port_bt.tail = port_bt.head;   /* 이전 속도로 받은 깨진 글자 버리기 */
  port_bt.len  = 0;
  HAL_UART_Receive_IT(&huart1, &port_bt.rx_byte, 1);
}

/* AT 중계 모드 시작: 모터 멈추고 HC-05 쪽을 38400으로 */
static void at_bridge_enter(void)
{
  set_speed(0, 0);
  bt_set_baud(BT_BAUD_AT);
  at_bridge = 1;
  printf("=== HC-05 AT mode (%d bps) ===\r\n", BT_BAUD_AT);
  printf("1) Unplug HC-05 VCC\r\n");
  printf("2) Hold the button on HC-05 and plug VCC back in\r\n");
  printf("3) LED blinks slowly (2s on / 2s off) -> release button\r\n");
  printf("Type AT commands (AT, AT+PSWD?, AT+UART? ...). EXIT to quit.\r\n> ");
}

/* AT 중계 모드 끝: HC-05 쪽을 평소 속도(9600)로 되돌림 */
static void at_bridge_exit(void)
{
  at_bridge = 0;
  bt_set_baud(BT_BAUD_DATA);
  printf("=== AT mode off. Unplug/replug HC-05 VCC (without button) ===\r\n> ");
}

/* AT 중계 모드 동작
 * - HC-05가 보낸 글자 → 그대로 PC 터미널에 출력
 * - PC에서 친 줄 → Enter 치면 끝에 CR+LF 붙여서 HC-05로 전송 (AT 명령은 CR+LF로 끝나야 함) */
static void at_bridge_poll(void)
{
  /* HC-05 → PC */
  while (port_bt.tail != port_bt.head) {
    uint8_t c = port_bt.ring[port_bt.tail & (RX_RING_SIZE - 1)];
    port_bt.tail++;
    HAL_UART_Transmit(&huart2, &c, 1, HAL_MAX_DELAY);
  }

  /* PC → HC-05 (한 줄씩) */
  cmd_port_t *p = &port_pc;
  while (p->tail != p->head) {
    char c = (char)p->ring[p->tail & (RX_RING_SIZE - 1)];
    p->tail++;

    if (c == '\r' || c == '\n') {
      if (p->len > 0) {
        p->line[p->len] = '\0';
        printf("\r\n");
        if (str_eq_nocase(p->line, "EXIT")) {
          p->len = 0;
          at_bridge_exit();
          return;
        }
        HAL_UART_Transmit(&huart1, (uint8_t *)p->line, p->len, HAL_MAX_DELAY);
        HAL_UART_Transmit(&huart1, (uint8_t *)"\r\n", 2, HAL_MAX_DELAY);
        p->len = 0;
      }
    } else if (c == '\b' || c == 0x7F) {
      if (p->len > 0) { p->len--; printf("\b \b"); }
    } else if (p->len < CMD_LINE_MAX - 1) {
      p->line[p->len++] = c;
      HAL_UART_Transmit(&huart2, (uint8_t *)&c, 1, HAL_MAX_DELAY);  /* 에코 */
    }
  }
}

/* 수신 인터럽트에서 부름: 받은 1글자를 링버퍼에 넣고 다음 1글자 수신을 다시 걸어둠 */
static void port_rx_isr(cmd_port_t *p)
{
  p->ring[p->head & (RX_RING_SIZE - 1)] = p->rx_byte;
  p->head++;
  HAL_UART_Receive_IT(p->huart, &p->rx_byte, 1);
}
/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_TIM1_Init();
  MX_TIM2_Init();
  MX_TIM3_Init();
  MX_USART2_UART_Init();
  MX_TIM6_Init();
  MX_USART1_UART_Init();
  MX_I2C1_Init();
  /* USER CODE BEGIN 2 */
  /* 1) PWM 출력 시작: CubeMX는 설정만 해두고, 실제 출력은 여기서 켜야 함 */
  HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
  HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_2);

  /* 2) 엔코더 카운트 시작 (A상·B상 둘 다 사용) */
  HAL_TIM_Encoder_Start(&htim2, TIM_CHANNEL_ALL);
  HAL_TIM_Encoder_Start(&htim3, TIM_CHANNEL_ALL);
  enc_left_prev  = (uint16_t)__HAL_TIM_GET_COUNTER(&htim2);
  enc_right_prev = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);

  /* 3) 정지 상태로 시작한 뒤 TB6612 깨우기 (STBY = HIGH) */
  motor_stop();
  HAL_GPIO_WritePin(STBY_GPIO_Port, STBY_Pin, GPIO_PIN_SET);

  printf("\r\n=== firecar command mode ===\r\n");
  printf("Hands off: calibrating in %d s...\r\n", BOOT_WAIT_MS / 1000);
  HAL_Delay(BOOT_WAIT_MS);   /* 전원 넣고 손 뗄 시간 → 그다음 자이로 영점을 잡으므로 차를 건드리지 않기 */

  /* 3-1) I2C 센서 확인 + MPU6050 영점 잡기 (약 1초, 이때 차를 건드리지 않기) */
  i2c_scan();
  imu_init();
  odom_reset();     /* 켠 자리 = 집(출발점) */

  /* 4) 10ms 제어 타이머 시작 → 이때부터 HAL_TIM_PeriodElapsedCallback이 10ms마다 불림 */
  HAL_TIM_Base_Start_IT(&htim6);

  /* 5) UART 1글자 수신 인터럽트 시작 (PC, 블루투스 둘 다)
   *    → 글자가 오면 HAL_UART_RxCpltCallback 호출 */
  HAL_UART_Receive_IT(port_pc.huart, &port_pc.rx_byte, 1);
  HAL_UART_Receive_IT(port_bt.huart, &port_bt.rx_byte, 1);
  print_help();

  out_uart = &huart1;
  printf("firecar BT ready (H: help)\r\n");   /* 폰이 연결돼 있으면 보임 */
  out_uart = &huart2;
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    /* 받은 글자가 있으면 명령으로 처리 (PID는 TIM6 인터럽트에서 따로 돌고 있음) */
    if (at_bridge) {
      at_bridge_poll();        /* HC-05 설정 중: PC ↔ HC-05 중계만 */
    } else {
      uart_poll_commands();    /* 평소: 명령 처리 */
      imu_update();            /* 자이로 읽어서 각도 누적 */
      turn_update();           /* T 명령 회전 중이면 속도 조절·도착 판단 */
      drive_update();          /* D 명령 이동 중이면 속도·방향 조절, 도착 판단 */
      odom_update();           /* 엔코더 + 자이로로 현재 위치 (x, y) 갱신 */
      homing_update();         /* G 귀소 중이면 다음 단계로 진행 */
      check_cmd_timeout();
    }
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */
/* 타이머 주기 인터럽트 콜백: HAL이 TIM6 업데이트 인터럽트마다(10ms) 불러줌 */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM6) {
    speed_control_step();
  }
}

/* UART 1글자 수신 완료 콜백: 어느 UART인지 보고 그 통로의 링버퍼에 넣음
 * (HAL_UART_Receive_IT는 1번 받으면 끝나므로 port_rx_isr에서 매번 다시 호출) */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  if (huart->Instance == USART2)      port_rx_isr(&port_pc);
  else if (huart->Instance == USART1) port_rx_isr(&port_bt);
}

/* 수신 에러(오버런 등)가 나면 HAL이 수신을 멈추므로 다시 시작 */
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
  if (huart->Instance == USART2)      HAL_UART_Receive_IT(&huart2, &port_pc.rx_byte, 1);
  else if (huart->Instance == USART1) HAL_UART_Receive_IT(&huart1, &port_bt.rx_byte, 1);
}
/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
