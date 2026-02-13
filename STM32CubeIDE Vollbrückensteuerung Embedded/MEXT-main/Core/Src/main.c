/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
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
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define RX_SZ 5
#define PREAMBLE 0xFF // START HEX für UART COM

#define PUTCHAR_PROTOTYPE int __io_putchar(int ch)

static uint8_t rx[RX_SZ]={0};
static uint8_t rx_buf[RX_SZ];

// CMD-Base
#define CMD_SET		 0x10
#define CMD_START	 0x20
#define CMD_STOP	 0x30
#define CMD_READBACK 0x40

// TIMER GRENZEN
#define T1_US_MIN   10u
#define T1_US_MAX   1000u
#define T2_MS_MIN   1u           // Protokoll in ms; Timer könnte 0.5 ms, siehe Kommentar
#define T2_MS_MAX   10000u       // 10 s

// Prescaler-Fakten über .ioc FEST konfiguriert (bei TIMCLK=170 MHz, APBx=1):
// TIM1: PSC=1699 -> Tick=10 µs
// TIM2: PSC=16999-> Tick=100 µs

uint8_t tim1_state_cnt = 0;
uint8_t tim2_pulse_cnt = 0;
uint8_t state = 0;

uint8_t pulse_count = 0;
uint8_t soll_pulse_count = 10;

uint8_t volatile command_rcv = 0;

// einfache Ablage der zuletzt gesetzten Werte
typedef struct { uint16_t value; uint8_t flags; } tcfg_t;
static volatile tcfg_t Tcfg[2] = {0};   // [0]=TIM1, [1]=TIM2

/* ====== STATE ====== */
typedef enum { ST_IDLE = 0, ST_RUN = 1 } run_state_t;
typedef enum { EXIT_NONE = 0, EXIT_SOFT, EXIT_HARD } exit_mode_t;

static volatile run_state_t g_state = ST_IDLE;
static volatile uint8_t     g_t1_cnt = 0;
static volatile exit_mode_t g_exit   = EXIT_NONE;


/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

TIM_HandleTypeDef htim1;
TIM_HandleTypeDef htim2;

UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_TIM1_Init(void);
static void MX_TIM2_Init(void);
/* USER CODE BEGIN PFP */

/* ====== GPIO SHORTCUTS (ersetze Ports/Pins durch deine Cube-Makros!) ====== */
static inline void Enable_Right(bool on){ HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, on?GPIO_PIN_SET:GPIO_PIN_RESET); }
static inline void Enable_Left (bool on){ HAL_GPIO_WritePin(GPIOC, GPIO_PIN_7, on?GPIO_PIN_SET:GPIO_PIN_RESET); }
static inline void Drive_Right (bool on){ HAL_GPIO_WritePin(GPIOA, GPIO_PIN_9, on?GPIO_PIN_SET:GPIO_PIN_RESET); }
static inline void Drive_Left  (bool on){ HAL_GPIO_WritePin(GPIOA, GPIO_PIN_8, on?GPIO_PIN_SET:GPIO_PIN_RESET); }

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/*++++++++++++ Puls Form Helfer ++++++++++++ */
/* Aktionen für Puls 1/2 – hier nur Beispiel, setz was du brauchst */
static inline void positive_pulse_actions(void){
	// ----- Halbbrücke links High Side aktiv -----
	Drive_Left(true);
	Enable_Left(true);
	// ----- Halbbrücke rechts Low Side aktiv -----
	Drive_Right(false);
    Enable_Right(true);
}
static inline void negative_pulse_actions(void){
	// ----- Halbbrücke links High Side aktiv -----
	Drive_Left(false);
	Enable_Left(true);
	// ----- Halbbrücke rechts Low Side aktiv -----
	Drive_Right(true);
    Enable_Right(true);
}

static inline void all_off(void){
	// alle aus
    Enable_Right(false);
    Enable_Left(false);
    Drive_Right(false);
    Drive_Left(false);
}


static inline TIM_HandleTypeDef* tim_by_id(uint8_t timer)
{
	return (timer == 2) ? &htim2 : &htim1; // if timer == 2 return &htim2 else return &htim1
}

static void apply_set(uint8_t timer, uint16_t period_field, uint8_t flags)
{

	TIM_HandleTypeDef *ht =  tim_by_id(timer); // Timer Handle ermitteln

	HAL_TIM_Base_Stop(ht); // Timer stopppen für sichere konfiguration
	__HAL_TIM_CLEAR_FLAG(ht, TIM_FLAG_UPDATE); // (UIF=)Update Interrupt Flag - Bit löschen

	uint32_t ticks = 1;

	if (timer == 1){
        // --- FAST: period_field in µs ---
        uint32_t us = period_field;
        if (us < T1_US_MIN) us = T1_US_MIN;
        if (us > T1_US_MAX) us = T1_US_MAX;

        // Tick = 10 µs  -> ticks = us / 10  (runden auf nächste Ganzzahl)
        ticks = (us + 5u) / 10u;            // 10..100 -> 1..10..100
        if (ticks == 0) ticks = 1;          // Schutz

        Tcfg[timer-1].value = (uint16_t)us;   // READBACK in µs
	} else {
		 // --- SLOW: period_field in ms ---
		uint32_t ms = period_field;
		if (ms < T2_MS_MIN) ms = T2_MS_MIN;     // Protokoll: min 1 ms (Timer könnte 0.5 ms)
		if (ms > T2_MS_MAX) ms = T2_MS_MAX;

		// Tick = 100 µs -> 1 ms = 10 Ticks
		ticks = ms * 10u;                       // 1..10000 ms -> 10..100000 Ticks
		if (ticks < 5u) ticks = 5u;             // Timer-Kapazität: min 0.5 ms (ARR>=4), nur falls 0.5 ms noch gewünscht ist
		if (ticks > 100000u) ticks = 100000u;   // 10 s Grenze

		Tcfg[timer-1].value = (uint16_t)ms;    // READBACK in ms
	}

	__HAL_TIM_SET_AUTORELOAD(ht, (ticks - 1u)); // TImer zählt von 0 bis ARR = period - 1 (period-Anzahl an ticks)
    __HAL_TIM_SET_COUNTER(ht, 0u);

	Tcfg[timer-1].flags = flags;	// FLAGS (Soft / Hard-Exit)
}

static void do_start(uint8_t timer)
{
    TIM_HandleTypeDef *ht = tim_by_id(timer); 	// Timer-Handle ermitteln
    __HAL_TIM_SET_COUNTER(ht, 0);				// Counter auf 0 setzen
    __HAL_TIM_CLEAR_FLAG(ht, TIM_FLAG_UPDATE);	// UIF-Bit löschen
    HAL_TIM_Base_Start_IT(ht);					// Interrupt-Timer armen
}

static void do_stop(uint8_t timer)
{
    TIM_HandleTypeDef *ht = tim_by_id(timer);	// Timer-Handle ermitteln
    HAL_TIM_Base_Stop_IT(ht);					// Interrupt-Timer stoppen
    __HAL_TIM_CLEAR_FLAG(ht, TIM_FLAG_UPDATE);	// UIF-Bit löschen
}

static void send_readback(uint8_t timer)
{
    uint8_t tx[5];
    uint16_t p = Tcfg[timer-1].value;
    tx[0] = PREAMBLE;
    tx[1] = CMD_READBACK + (timer == 2 ? 1 : 0);  // 0x40/0x41
    tx[2] = (uint8_t)(p & 0xFF);                  // LSB
    tx[3] = (uint8_t)(p >> 8);                    // MSB
    tx[4] = Tcfg[timer-1].flags;
    HAL_UART_Transmit(&huart2, tx, sizeof tx, 100);	// TODO: hier über printf testen
    // HAL_UART_Transmit(&huart2, (uint8_t *)&ch, 1, 100); => hierdurch unten, geht UART_Transmit auch über printf, drüber testen
}






/* =============== API Funktionen =============== */
void seq_start(void)
{
    if (g_state != ST_IDLE) return;
    g_exit   = EXIT_NONE;
    g_t1_cnt = 0;

    __HAL_TIM_SET_COUNTER(&htim1, 0);
    __HAL_TIM_SET_COUNTER(&htim2, 0);
    __HAL_TIM_CLEAR_FLAG(&htim1, TIM_FLAG_UPDATE);
    __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE);

    HAL_TIM_Base_Start_IT(&htim1);   // "Fast" – triggert Puls 1 und Puls 2
    HAL_TIM_Base_Start_IT(&htim2);   // "Slow" – Zyklusende

    g_state = ST_RUN;
}

void seq_request_soft_stop(void) { g_exit = EXIT_SOFT; }   // stoppen nach Puls2 / Zyklusende
void seq_hard_stop(void)
{
    HAL_TIM_Base_Stop_IT(&htim1);
    HAL_TIM_Base_Stop_IT(&htim2);
    __HAL_TIM_CLEAR_FLAG(&htim1, TIM_FLAG_UPDATE);
    __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE);
    all_off();
    g_state = ST_IDLE;
    g_t1_cnt = 0;
    g_exit   = EXIT_NONE;
}


/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  /* ----------- Helper Functions ----------- */


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
  MX_TIM1_Init();
  MX_TIM2_Init();
  /* USER CODE BEGIN 2 */


  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */

  // Diese Funktion empfängt über Interrupt UART Signale aus dem Python Skript
  HAL_UARTEx_ReceiveToIdle_IT(&huart2, rx, RX_SZ); // Prozessstart


while (1)
{
	if(command_rcv == 1){
		command_rcv = 0;

        const uint8_t  cmd   = rx_buf[1];
        const uint8_t  base  = cmd & 0xF0;            // 0x10/0x20/0x30/0x40
        const uint8_t  timer = (cmd & 0x01) ? 2 : 1;  // ungerade -> TIM2
        const uint16_t value = (uint16_t)rx_buf[2] | ((uint16_t)rx_buf[3] << 8); // LSB,MSB
        const uint8_t  flags  = rx_buf[4];

        switch (base) {
        case CMD_SET:      /* 0x10 / 0x11 */
        	// Setzt adressierten Timer:
        	//  - TIM1: interpretiert value als µs (10..1000, Tick=10µs)
			//  - TIM2: interpretiert value als ms  (1..10000, Tick=0.1ms)
			apply_set(timer, value, flags);
			printf("CMD: SET %s OK (period=%u)\r\n", (timer==1?"T1":"T2"), (unsigned)value);
			break;

		case CMD_START:    /* 0x20 / 0x21 */
			//alternativ für nur einen Timer => do_start(timer);
			// Anzahl Pulse setzen
			soll_pulse_count = value;
			// Start beider Timer + State Machine
			seq_start();
            printf("CMD: START (seq) OK\r\n");
            break;

		case CMD_STOP:     /* 0x30 / 0x31 */
            // Immer SOFT-STOP: am Zyklusende (TIM2-IRQ) in all_off() beenden
		  if (g_exit == EXIT_HARD) { seq_hard_stop(); return; }
            seq_request_soft_stop();
            printf("CMD: STOP (soft) requested\r\n");
            break;

		case CMD_READBACK: /* 0x40 / 0x41 */
            // READBACK spiegelt die gesetzten Einheiten zurück:
            //  - T1: µs
            //  - T2: ms
            send_readback(timer);
            printf("CMD: READBACK %s OK\r\n", (timer==1?"T1":"T2"));
            break;

		default:
			printf("Unknown CMD: 0x%02X\r\n", cmd);
			break;
		}

        printf("RX:");
        for (uint8_t i = 0; i < RX_SZ; ++i) printf(" %02X", rx_buf[i]);
        printf("\r\n");

	 // SET GPIO 1 - 4
	 // switch mit Mode Variable


	}
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
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
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1_BOOST);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = RCC_PLLM_DIV4;
  RCC_OscInitStruct.PLL.PLLN = 85;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV2;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief TIM1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM1_Init(void)
{

  /* USER CODE BEGIN TIM1_Init 0 */

  /* USER CODE END TIM1_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM1_Init 1 */

  /* USER CODE END TIM1_Init 1 */
  htim1.Instance = TIM1;
  htim1.Init.Prescaler = 1699;
  htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim1.Init.Period = 0;
  htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim1.Init.RepetitionCounter = 0;
  htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim1) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim1, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterOutputTrigger2 = TIM_TRGO2_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim1, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM1_Init 2 */

  /* USER CODE END TIM1_Init 2 */

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */

  /* USER CODE END TIM2_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 16999;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 4294967295;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim2, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */

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
  huart2.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart2.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  huart2.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&huart2, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&huart2, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&huart2) != HAL_OK)
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
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, LD2_Pin|Drive_Left_Pin|Drive_Right_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(Enable_Left_GPIO_Port, Enable_Left_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(Enable_Right_GPIO_Port, Enable_Right_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : B1_Pin PC0 PC1 */
  GPIO_InitStruct.Pin = B1_Pin|GPIO_PIN_0|GPIO_PIN_1;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pins : LD2_Pin Drive_Left_Pin Drive_Right_Pin */
  GPIO_InitStruct.Pin = LD2_Pin|Drive_Left_Pin|Drive_Right_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pin : Enable_Left_Pin */
  GPIO_InitStruct.Pin = Enable_Left_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(Enable_Left_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : Enable_Right_Pin */
  GPIO_InitStruct.Pin = Enable_Right_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(Enable_Right_GPIO_Port, &GPIO_InitStruct);

  /* EXTI interrupt init*/
  HAL_NVIC_SetPriority(EXTI15_10_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */




void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size){

	if(huart->Instance == USART2){
        if (Size == RX_SZ && rx[0] == PREAMBLE) {
    		memcpy(rx_buf, rx, Size); // Daten sichern
            command_rcv = 1;		  // Kommando erhalten Flag setzen
        }

		// 2) Optional: Quellpuffer leeren (hilft beim Debugging)
		// memset(rx, 0, RX_SZ);

	HAL_UARTEx_ReceiveToIdle_IT(&huart2, rx, RX_SZ); // immer wieder neu armen

	}
}

PUTCHAR_PROTOTYPE
{
  /* Place your implementation of fputc here */
  /* e.g. write a character to the USART2 and Loop until the end of transmission */
  HAL_UART_Transmit(&huart2, (uint8_t *)&ch, 1, 100);

  return ch;
}

// Callback
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  /* ============== TIM1: schnelle Ereignisse im Zyklus ============== */
  if (htim->Instance == TIM1)
  {
	  if (g_state != ST_RUN) return; // damit das abfängt muss in Start-Sequenz g_state = ST_RUN gesetzt werden

	  switch (g_t1_cnt)
	  {
		  case 0:     // erstes fast-Event -> Positiver Puls 1
			  positive_pulse_actions();
			  g_t1_cnt = 1;
			  break;

		  case 1:     // zweites fast-Event -> Negativer Puls 2
			  negative_pulse_actions();
			  g_t1_cnt = 2;
			  break;

		  case 2:
			  // ab jetzt keine weiteren Fast-Events im laufenden Zyklus
			  all_off();
			  HAL_TIM_Base_Stop_IT(&htim1);
			  __HAL_TIM_CLEAR_FLAG(&htim1, TIM_FLAG_UPDATE);

		  default:
			  // ignorieren (TIM1 ist eigentlich schon gestoppt)
			  break;
	  }
  }

  /* ============== TIM2: Zyklusende ============== */
  else if (htim->Instance == TIM2)
  {
	  if (g_state != ST_RUN) return;

//	  if (soll_pulse_count != 0 && pulse_count >= soll_pulse_count-1){
//		  g_exit = EXIT_SOFT;
//	  }

	  // Softstop behandeln
	  if (g_exit == EXIT_SOFT) {
		  // nur an Zyklusende aussteigen
		  HAL_TIM_Base_Stop_IT(&htim2);
		  __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE);
		  g_state = ST_IDLE;
		  g_t1_cnt = 0;
		  g_exit = EXIT_NONE;
		  return;
	  }

	  // Weiterlaufen: neuen Zyklus vorbereiten
	  g_t1_cnt = 0;
	  pulse_count++;
	  __HAL_TIM_SET_COUNTER(&htim1, 0);
	  __HAL_TIM_CLEAR_FLAG(&htim1, TIM_FLAG_UPDATE);
	  HAL_TIM_Base_Start_IT(&htim1);   // nächste Puls-Folge im neuen Zyklus
  	  }

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

#ifdef  USE_FULL_ASSERT
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
