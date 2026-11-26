/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body (STM32F446RET6 + TIM6 + TIM2 PWM + DHT11 + XKC-Y26-V + CO ADC)
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

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
typedef struct
{
  uint8_t humidity;
  uint8_t temperature;
} DHT11_Data_t;

typedef struct
{
  uint16_t raw;
  uint32_t voltage_mv;
} CO_Data_t;
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define WATER_PORT              GPIOC
#define WATER_PIN               GPIO_PIN_2

#define DHT11_PORT              GPIOC
#define DHT11_PIN               GPIO_PIN_0

#define CO_PORT                 GPIOC
#define CO_PIN                  GPIO_PIN_1
#define CO_ADC_CHANNEL          ADC_CHANNEL_11
#define VREF_MV                 3300U
#define ADC_MAX_VALUE           4095U

/* Arduino D3 -> Nucleo-F446RE PB3 (TIM2_CH2 PWM -> IRF520 MOSFET) */
#define PUMP_PORT               GPIOB
#define PUMP_PIN                GPIO_PIN_3
#define PUMP_TIM_CHANNEL        TIM_CHANNEL_2
#define PUMP_PWM_PERIOD         999U      /* 1MHz / (999 + 1) = 1kHz PWM */
#define PUMP_MAX_SPEED_PCT      100U      /* 최대속도: 100% 듀티 */

/* 임계값 설정 */
#define TEMP_THRESHOLD_C        20U       /* 온도 20도 이상 */
#define CO_THRESHOLD_RAW        200U      /* CO ADC Raw 150 이상 */
#define WATER_REQUIRE_DETECTED  0U        /* 1: 수위 HIGH일 때만 펌프 구동, 0: 수위 무관 */

#define DEBOUNCE_MS             100U
#define HEARTBEAT_MS            2000U
#define DHT11_INTERVAL_MS       2000U
#define CO_INTERVAL_MS          2000U
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;

TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim6;

UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */
static uint8_t g_current_speed_pct = 0U;
static bool g_has_temp = false;
static uint8_t g_last_temp_c = 0U;
static bool g_has_co = false;
static uint16_t g_last_co_raw = 0U;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_TIM6_Init(void);
static void MX_ADC1_Init(void);
static void MX_TIM2_Init(void);
/* USER CODE BEGIN PFP */
static void UART_Print(const char *msg);
static void Print_Water_Status(bool detected, uint32_t tick_ms, bool is_change);
static void Delay_us(uint16_t us);
static void DHT11_Set_Pin_Output(void);
static void DHT11_Set_Pin_Input(void);
static uint32_t DHT11_Wait_Pin_State(GPIO_PinState target, uint16_t timeout_us);
static bool DHT11_Read(DHT11_Data_t *out);
static void Print_DHT11_Status(const DHT11_Data_t *data, bool ok, uint32_t tick_ms);
static bool CO_Read(CO_Data_t *out);
static void Print_CO_Status(const CO_Data_t *data, bool ok, uint32_t tick_ms);
static void Pump_SetSpeedPct(uint8_t speed_pct, uint32_t tick_ms, const char *reason);
static void Pump_EvaluateControl(bool water_detected, uint32_t tick_ms);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static void UART_Print(const char *msg)
{
  if (msg != NULL)
  {
    HAL_UART_Transmit(&huart2, (uint8_t *)msg, (uint16_t)strlen(msg), HAL_MAX_DELAY);
  }
}

static void Print_Water_Status(bool detected, uint32_t tick_ms, bool is_change)
{
  char buf[128];
  const char *tag = is_change ? "변화" : "상태";
  const char *state_str = detected ? "물 감지됨 (HIGH)" : "물 없음 (LOW)";

  snprintf(buf, sizeof(buf), "[%lums] [%s] PC2 = %s | 수위: %s\r\n",
           (unsigned long)tick_ms,
           tag,
           detected ? "HIGH(1)" : "LOW(0)",
           state_str);

  UART_Print(buf);
}

static void Delay_us(uint16_t us)
{
  __HAL_TIM_SET_COUNTER(&htim6, 0U);
  while (__HAL_TIM_GET_COUNTER(&htim6) < us)
  {
    __NOP();
  }
}

static void DHT11_Set_Pin_Output(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  GPIO_InitStruct.Pin = DHT11_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(DHT11_PORT, &GPIO_InitStruct);
}

static void DHT11_Set_Pin_Input(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  GPIO_InitStruct.Pin = DHT11_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(DHT11_PORT, &GPIO_InitStruct);
}

static uint32_t DHT11_Wait_Pin_State(GPIO_PinState target, uint16_t timeout_us)
{
  __HAL_TIM_SET_COUNTER(&htim6, 0U);
  while (HAL_GPIO_ReadPin(DHT11_PORT, DHT11_PIN) != target)
  {
    if (__HAL_TIM_GET_COUNTER(&htim6) >= timeout_us)
    {
      return 0U;
    }
    __NOP();
  }
  return (uint32_t)__HAL_TIM_GET_COUNTER(&htim6);
}

static bool DHT11_Read(DHT11_Data_t *out)
{
  uint8_t raw[5] = {0};

  if (out == NULL)
  {
    return false;
  }

  /* 1. 시작 신호: 18ms LOW 후 30us HIGH */
  DHT11_Set_Pin_Output();
  HAL_GPIO_WritePin(DHT11_PORT, DHT11_PIN, GPIO_PIN_RESET);
  HAL_Delay(18);
  HAL_GPIO_WritePin(DHT11_PORT, DHT11_PIN, GPIO_PIN_SET);
  Delay_us(30U);

  /* 2. 센서 응답 대기 (약 80us LOW -> 약 80us HIGH -> 데이터 시작 LOW) */
  DHT11_Set_Pin_Input();
  if (DHT11_Wait_Pin_State(GPIO_PIN_RESET, 100U) == 0U)
  {
    return false;
  }
  if (DHT11_Wait_Pin_State(GPIO_PIN_SET, 100U) == 0U)
  {
    return false;
  }
  if (DHT11_Wait_Pin_State(GPIO_PIN_RESET, 100U) == 0U)
  {
    return false;
  }

  /* 3. 40비트(5바이트) 수신: HIGH 진입 후 40us 뒤에도 HIGH면 비트 '1' */
  for (uint8_t byte_idx = 0U; byte_idx < 5U; byte_idx++)
  {
    uint8_t val = 0U;
    for (uint8_t bit_idx = 0U; bit_idx < 8U; bit_idx++)
    {
      if (DHT11_Wait_Pin_State(GPIO_PIN_SET, 100U) == 0U)
      {
        return false;
      }

      Delay_us(40U);
      if (HAL_GPIO_ReadPin(DHT11_PORT, DHT11_PIN) == GPIO_PIN_SET)
      {
        val |= (uint8_t)(1U << (7U - bit_idx));
        if (DHT11_Wait_Pin_State(GPIO_PIN_RESET, 100U) == 0U)
        {
          return false;
        }
      }
    }
    raw[byte_idx] = val;
  }

  /* 4. 체크섬 확인 */
  uint8_t sum = (uint8_t)(raw[0] + raw[1] + raw[2] + raw[3]);
  if (sum != raw[4])
  {
    return false;
  }

  out->humidity = raw[0];
  out->temperature = raw[2];
  return true;
}

static void Print_DHT11_Status(const DHT11_Data_t *data, bool ok, uint32_t tick_ms)
{
  char buf[128];
  if (ok && (data != NULL))
  {
    snprintf(buf, sizeof(buf), "[%lums] [DHT11] PC0 | 온도: %u C, 습도: %u%%\r\n",
             (unsigned long)tick_ms,
             (unsigned int)data->temperature,
             (unsigned int)data->humidity);
  }
  else
  {
    snprintf(buf, sizeof(buf), "[%lums] [DHT11] PC0 | 읽기 실패 (배선/풀업/Prescaler 확인)\r\n",
             (unsigned long)tick_ms);
  }
  UART_Print(buf);
}

static bool CO_Read(CO_Data_t *out)
{
  if (out == NULL)
  {
    return false;
  }

  if (HAL_ADC_Start(&hadc1) != HAL_OK)
  {
    return false;
  }

  if (HAL_ADC_PollForConversion(&hadc1, 10U) != HAL_OK)
  {
    HAL_ADC_Stop(&hadc1);
    return false;
  }

  uint32_t adc_val = HAL_ADC_GetValue(&hadc1);
  HAL_ADC_Stop(&hadc1);

  out->raw = (uint16_t)adc_val;
  out->voltage_mv = (adc_val * VREF_MV) / ADC_MAX_VALUE;
  return true;
}

static void Print_CO_Status(const CO_Data_t *data, bool ok, uint32_t tick_ms)
{
  char buf[128];
  if (ok && (data != NULL))
  {
    snprintf(buf, sizeof(buf), "[%lums] [CO] PC1(IN11) | ADC: %u / %u, 전압: %lu mV\r\n",
             (unsigned long)tick_ms,
             (unsigned int)data->raw,
             (unsigned int)ADC_MAX_VALUE,
             (unsigned long)data->voltage_mv);
  }
  else
  {
    snprintf(buf, sizeof(buf), "[%lums] [CO] PC1(IN11) | ADC 읽기 실패\r\n",
             (unsigned long)tick_ms);
  }
  UART_Print(buf);
}

static void Pump_SetSpeedPct(uint8_t speed_pct, uint32_t tick_ms, const char *reason)
{
  uint32_t pulse;

  if (speed_pct > 100U)
  {
    speed_pct = 100U;
  }

  /* Period=999(1000클럭) 기준 100%일 때 pulse=1000으로 최대 출력 */
  pulse = ((uint32_t)speed_pct * (PUMP_PWM_PERIOD + 1U)) / 100U;
  __HAL_TIM_SET_COMPARE(&htim2, PUMP_TIM_CHANNEL, pulse);

  if (g_current_speed_pct != speed_pct)
  {
    char buf[160];
    g_current_speed_pct = speed_pct;
    snprintf(buf, sizeof(buf), "[%lums] [PUMP PWM] PB3(D3) -> 속도 %u%% (CCR=%lu) [%s]\r\n",
             (unsigned long)tick_ms,
             (unsigned int)speed_pct,
             (unsigned long)pulse,
             (reason != NULL) ? reason : "제어");
    UART_Print(buf);
  }
}

static void Pump_EvaluateControl(bool water_detected, uint32_t tick_ms)
{
  bool temp_triggered = (g_has_temp && (g_last_temp_c >= TEMP_THRESHOLD_C));
  bool co_triggered = (g_has_co && (g_last_co_raw >= CO_THRESHOLD_RAW));
  bool env_triggered = (temp_triggered || co_triggered);

#if WATER_REQUIRE_DETECTED
  if (!water_detected)
  {
    Pump_SetSpeedPct(0U, tick_ms, "수위 LOW - 공회전 방지 정지");
    return;
  }
#else
  (void)water_detected;
#endif

  if (env_triggered)
  {
    const char *reason = (temp_triggered && co_triggered) ? "온도>=20C & CO>=150" :
                         (temp_triggered) ? "온도>=20C" : "CO>=150";
    Pump_SetSpeedPct(PUMP_MAX_SPEED_PCT, tick_ms, reason);
  }
  else
  {
    Pump_SetSpeedPct(0U, tick_ms, "임계값 미만 - 정지");
  }
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
  MX_USART2_UART_Init();
  MX_TIM6_Init();
  MX_ADC1_Init();
  MX_TIM2_Init();
  /* USER CODE BEGIN 2 */
  if (HAL_TIM_Base_Start(&htim6) != HAL_OK)
  {
    Error_Handler();
  }

  if (HAL_TIM_PWM_Start(&htim2, PUMP_TIM_CHANNEL) != HAL_OK)
  {
    Error_Handler();
  }

  /* 시작 시 펌프 0% 정지 */
  g_current_speed_pct = 0xFFU; /* 최초 상태 출력 유도 */
  Pump_SetSpeedPct(0U, HAL_GetTick(), "초기화 정지");

  UART_Print("\r\n==================================================================================\r\n");
  UART_Print("  STM32F446RET6 | XKC-Y26-V(PC2) + DHT11(PC0) + CO(PC1) + TIM2 PWM(PB3/D3)\r\n");
  UART_Print("  조건: 온도 >= 20C 또는 CO(ADC) >= 150 -> PWM 최대속도(100%)\r\n");
  UART_Print("==================================================================================\r\n");

  bool raw_state = (HAL_GPIO_ReadPin(WATER_PORT, WATER_PIN) == GPIO_PIN_SET);
  bool stable_state = raw_state;
  uint32_t last_raw_change_tick = HAL_GetTick();
  uint32_t last_heartbeat_tick = HAL_GetTick();
  uint32_t last_dht11_tick = HAL_GetTick() - DHT11_INTERVAL_MS;
  uint32_t last_co_tick = HAL_GetTick() - CO_INTERVAL_MS;

  Print_Water_Status(stable_state, HAL_GetTick(), true);
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    uint32_t now = HAL_GetTick();
    bool current_raw = (HAL_GPIO_ReadPin(WATER_PORT, WATER_PIN) == GPIO_PIN_SET);

    /* 수위 센서 신호 디바운스 처리 */
    if (current_raw != raw_state)
    {
      raw_state = current_raw;
      last_raw_change_tick = now;
    }

    if ((current_raw != stable_state) && ((now - last_raw_change_tick) >= DEBOUNCE_MS))
    {
      stable_state = current_raw;
      Print_Water_Status(stable_state, now, true);
      last_heartbeat_tick = now;
      Pump_EvaluateControl(stable_state, now);
    }

    /* 2초마다 수위 상태 요약 출력 */
    if ((now - last_heartbeat_tick) >= HEARTBEAT_MS)
    {
      last_heartbeat_tick = now;
      Print_Water_Status(stable_state, now, false);
    }

    /* 2초마다 DHT11 온습도 읽기 및 출력 */
    if ((now - last_dht11_tick) >= DHT11_INTERVAL_MS)
    {
      last_dht11_tick = now;
      DHT11_Data_t dht_data = {0};
      bool dht_ok = DHT11_Read(&dht_data);
      Print_DHT11_Status(&dht_data, dht_ok, now);

      if (dht_ok)
      {
        g_has_temp = true;
        g_last_temp_c = dht_data.temperature;
        Pump_EvaluateControl(stable_state, now);
      }
    }

    /* 2초마다 일산화탄소(CO) 센서 ADC 읽기 및 출력 */
    if ((now - last_co_tick) >= CO_INTERVAL_MS)
    {
      last_co_tick = now;
      CO_Data_t co_data = {0};
      bool co_ok = CO_Read(&co_data);
      Print_CO_Status(&co_data, co_ok, now);

      if (co_ok)
      {
        g_has_co = true;
        g_last_co_raw = co_data.raw;
        Pump_EvaluateControl(stable_state, now);
      }
    }

    HAL_Delay(10);
  }
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
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

/**
  * @brief ADC1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_ADC1_Init(void)
{

  /* USER CODE BEGIN ADC1_Init 0 */
  __HAL_RCC_ADC1_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();

  GPIO_InitTypeDef GPIO_InitStruct = {0};
  GPIO_InitStruct.Pin = CO_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(CO_PORT, &GPIO_InitStruct);
  /* USER CODE END ADC1_Init 0 */

  ADC_ChannelConfTypeDef sConfig = {0};

  /* USER CODE BEGIN ADC1_Init 1 */

  /* USER CODE END ADC1_Init 1 */

  /** Configure the global features of the ADC (Clock, Resolution, Data Alignment and number of conversion)
  */
  hadc1.Instance = ADC1;
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV2;
  hadc1.Init.Resolution = ADC_RESOLUTION_12B;
  hadc1.Init.ScanConvMode = DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
  hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.NbrOfConversion = 1;
  hadc1.Init.DMAContinuousRequests = DISABLE;
  hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
  if (HAL_ADC_Init(&hadc1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure for the selected ADC regular channel its corresponding rank in the sequencer and its sample time.
  */
  sConfig.Channel = ADC_CHANNEL_11;
  sConfig.Rank = 1;
  sConfig.SamplingTime = ADC_SAMPLETIME_84CYCLES;
  if (HAL_ADC_ConfigChannel(&hadc1, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN ADC1_Init 2 */

  /* USER CODE END ADC1_Init 2 */

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */
  __HAL_RCC_TIM2_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  GPIO_InitTypeDef GPIO_InitStruct = {0};
  GPIO_InitStruct.Pin = PUMP_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF1_TIM2;
  HAL_GPIO_Init(PUMP_PORT, &GPIO_InitStruct);
  /* USER CODE END TIM2_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 4294967295;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */
  HAL_TIM_MspPostInit(&htim2);

}

/**
  * @brief TIM6 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM6_Init(void)
{

  /* USER CODE BEGIN TIM6_Init 0 */

  /* USER CODE END TIM6_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM6_Init 1 */

  /* USER CODE END TIM6_Init 1 */
  htim6.Instance = TIM6;
  htim6.Init.Prescaler = 15;
  htim6.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim6.Init.Period = 65535;
  htim6.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim6) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim6, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM6_Init 2 */

  /* USER CODE END TIM6_Init 2 */

}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* USER CODE END USART2_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pins : PC0 PC2 */
  GPIO_InitStruct.Pin = GPIO_PIN_0|GPIO_PIN_2;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pin : Water_sensor_Pin */
  GPIO_InitStruct.Pin = Water_sensor_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(Water_sensor_GPIO_Port, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
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
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
