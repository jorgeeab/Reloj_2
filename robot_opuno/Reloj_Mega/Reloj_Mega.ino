#include <AFMotor.h>
#include <FlowMeter.h>
#include <PID_v1.h>
#include <Servo.h>
#include <math.h>

// ======================= Motores =======================
AF_DCMotor motorAngulo(2);     // Motor angular (A)
AF_DCMotor motorCorredera(3);  // Motor lineal (X)
AF_DCMotor motorBomba(1);      // Bomba 5V

// ======================= Servo Z =======================
static const uint8_t SERVO_Z_PIN = 9; // Servo Z en pin 9
Servo servoZ;
float z_target_deg = 170.0f;     // 0°=arriba, 180°=abajo
float z_current_deg = 170.0f;
float z_speed_deg_s = 90.0f;    // velocidad por defecto (deg/s)
float z_mm_per_deg = 1.2121;      // conversión mm por grado
const float SERVO_MIN_DEG = 15.0f;  // límite superior mecánico (no subir más que 15°)
const float SERVO_MAX_DEG = 175.0f; // límite inferior mecánico
unsigned long lastServoUpdateMs = 0;

static inline float clampf(float v, float lo, float hi){ return (v<lo?lo:(v>hi?hi:v)); }

static void setServoImmediate(float deg){
  z_current_deg = clampf(deg, SERVO_MIN_DEG, SERVO_MAX_DEG);
  servoZ.write((int)z_current_deg);
}

static void applyServoRamp(unsigned long nowMs){
  unsigned long dtMs = nowMs - lastServoUpdateMs;
  if(dtMs == 0) return;
  lastServoUpdateMs = nowMs;
  float maxStep = z_speed_deg_s * (dtMs / 1000.0f);
  if(maxStep <= 0.0f) return;
  float delta = z_target_deg - z_current_deg;
  if(delta > maxStep) delta = maxStep;
  else if(delta < -maxStep) delta = -maxStep;
  z_current_deg = clampf(z_current_deg + delta, SERVO_MIN_DEG, SERVO_MAX_DEG);
  servoZ.write((int)z_current_deg);
}

// ======================= Calibraciones =======================
float pasosPorMM = 1.0;
float pasosPorGrado = 1.0;
float factorCalibracionFlujo = 1.0;  // Convierte unidades del FlowMeter a ml y ml/s
float caudalBombaMLs = 50.0;         // Caudal fijo de la bomba (ml/s) para control por tiempo

// ======================= Flujo / Volumen =======================
float caudalMLs = 0.0;               // ml/s
float volumenML = 0.0;               // ml acumulados
float volumenObjetivoML = 0.0;       // ml a bombear
int   resetVolumen = 0;
bool  usarSensorFlujo = true;        // true: sensor; false: por tiempo
unsigned long tiempoInicioBombeo = 0;

// ======================= Límites físicos =======================
const int LIMITE_MAX_X_MM = 400;     // mm
const int LIMITE_MAX_A_GRADOS = 360; // grados

// Pines de límites y encoders
const int PIN_LIMITE_MIN_X = 37;
#define PIN_ENCODER_B_X 40
#define PIN_ENCODER_A_X 42
int contadorDistancia = 0;   // para X
int estadoX = 0, ultimoEstadoX = 0;
int estadoLimiteX = 0;

#define PIN_ENCODER_B_A 48
#define PIN_ENCODER_A_A 50
const int PIN_LIMITE_MIN_A = 32;
int contadorAngulo = 0;      // para A
int estadoA = 0, ultimoEstadoA = 0;
int estadoLimiteA = 0;

// ======================= Flags & timing =======================
bool reiniciarX = true;
bool reiniciarA = true;

const unsigned long TIEMPO_ACTUALIZACION_FLUJO_MS = 100; // cada cuánto mido flujo/volumen
const unsigned long TIEMPO_MUESTREO_PID_MS = 100;        // sample time del PID
const unsigned long INTERVALO_ENVIO_MS = 300;            // envío por serial

unsigned long instanteFlujoAnterior = 0;
unsigned long instanteEnvioAnterior = 0;

// ======================= Control PID =======================
// Setpoints y entradas
double setpointX_mm = 0.0, posicionX_mm = 0.0;
double setpointA_deg = 0.0, angulo_deg = 0.0;

// Salidas PID (separadas de energías manuales)
double salidaPID_X = 0.0, salidaPID_A = 0.0;

// Energías manuales (y/o recibidas)
double energiaX = 0.0;        // corredera (X)
double energiaA = 0.0;        // ángulo (A)
double energiaBomba = 0.0;    // bomba (manual)

// Ganancias
double kpX = 1.0, kiX = 1.0, kdX = 0.2;
double kpA = 1.0, kiA = 1.0, kdA = 0.2;

// PIDs
PID pidX(&posicionX_mm, &salidaPID_X, &setpointX_mm, kpX, kiX, kdX, DIRECT);
PID pidA(&angulo_deg,    &salidaPID_A, &setpointA_deg, kpA, kiA, kdA, DIRECT);

// ======================= Flow Meter =======================
FlowMeter *medidorFlujo = nullptr;

// ======================= Energía mínima/máxima =======================
const int ENERGIA_MINIMA = 75;
const int ENERGIA_MAXIMA = 255;

// ======================= Modos por eje =======================
// codigoModo: bit0 = X manual, bit1 = A manual
uint8_t codigoModo = 0;

// ----------------------- Prototipos -----------------------
int remapearEnergia(int energia);
void ISRMedidor();
void iniciarMotores();
void iniciarMedidorFlujo();

void leerSensores();
void leerDistancia();
void leerAngulo();
void leerSensorFlujo();

void actualizarControlMotores();
void controlarMotoresReset();

void enviarDatos();
void recibirDatos();
void procesarComando(String command);

// ==========================================================
int remapearEnergia(int energia) {
  if (abs(energia) < ENERGIA_MINIMA && energia != 0) {
    return (energia > 0) ? ENERGIA_MINIMA : -ENERGIA_MINIMA;
  }
  return constrain(energia, -ENERGIA_MAXIMA, ENERGIA_MAXIMA);
}

void ISRMedidor() {
  if (medidorFlujo) medidorFlujo->count();
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_ENCODER_A_X, INPUT);
  pinMode(PIN_ENCODER_B_X, INPUT);
  pinMode(PIN_LIMITE_MIN_X, INPUT);

  pinMode(PIN_ENCODER_A_A, INPUT);
  pinMode(PIN_ENCODER_B_A, INPUT);
  pinMode(PIN_LIMITE_MIN_A, INPUT);

  iniciarMotores();
  iniciarMedidorFlujo();

  pidX.SetOutputLimits(-255, 255);
  pidA.SetOutputLimits(-255, 255);
  pidX.SetMode(AUTOMATIC);
  pidA.SetMode(AUTOMATIC);
  pidX.SetSampleTime(TIEMPO_MUESTREO_PID_MS);
  pidA.SetSampleTime(TIEMPO_MUESTREO_PID_MS);

  // Servo Z
  servoZ.attach(SERVO_Z_PIN);
  lastServoUpdateMs = millis();
  setServoImmediate(z_current_deg);
}

void loop() {
  recibirDatos();
  leerSensores();
  leerSensorFlujo();
  actualizarControlMotores();
  applyServoRamp(millis());
  enviarDatos();
}

// ======================= Inicialización =======================
void iniciarMotores() {
  motorAngulo.setSpeed(0);    motorAngulo.run(RELEASE);
  motorCorredera.setSpeed(0); motorCorredera.run(RELEASE);
  motorBomba.setSpeed(0);     motorBomba.run(RELEASE);
}

void iniciarMedidorFlujo() {
  // Sensor no calibrado en pin 2; ajustamos con factorCalibracionFlujo
  medidorFlujo = new FlowMeter(digitalPinToInterrupt(2), UncalibratedSensor, ISRMedidor, RISING);
}

// ======================= Sensores =======================
void leerSensorFlujo() {
  if (!usarSensorFlujo) return;

  unsigned long ahora = millis();
  if (ahora - instanteFlujoAnterior >= TIEMPO_ACTUALIZACION_FLUJO_MS) {
    unsigned long delta = ahora - instanteFlujoAnterior;
    instanteFlujoAnterior = ahora;

    medidorFlujo->tick(delta);

    // Nota: depende de la lib; escalamos con factorCalibracionFlujo a ml/s y ml
    float caudalBruto = medidorFlujo->getCurrentFlowrate();
    float volumenBruto = medidorFlujo->getTotalVolume();

    caudalMLs  = caudalBruto  * factorCalibracionFlujo; // ml/s
    volumenML  = volumenBruto * factorCalibracionFlujo; // ml
  }
}

void leerSensores() {
  estadoLimiteX = digitalRead(PIN_LIMITE_MIN_X);
  estadoLimiteA = digitalRead(PIN_LIMITE_MIN_A);
  leerDistancia();
  leerAngulo();
}

void leerDistancia() {
  estadoX = digitalRead(PIN_ENCODER_A_X);
  if (estadoX != ultimoEstadoX) {
    if (digitalRead(PIN_ENCODER_B_X) != estadoX) contadorDistancia++;
    else { if (contadorDistancia > 0) contadorDistancia--; else contadorDistancia = 0; }
  }
  ultimoEstadoX = estadoX;

  if (estadoLimiteX == HIGH) contadorDistancia = 0;
  posicionX_mm = (pasosPorMM != 0.0) ? (contadorDistancia / pasosPorMM) : contadorDistancia;
}

void leerAngulo() {
  estadoA = digitalRead(PIN_ENCODER_A_A);
  if (estadoA != ultimoEstadoA) {
    if (digitalRead(PIN_ENCODER_B_A) != estadoA) contadorAngulo++;
    else { if (contadorAngulo > 0) contadorAngulo--; else contadorAngulo = 0; }
  }
  ultimoEstadoA = estadoA;

  if (estadoLimiteA == HIGH) contadorAngulo = 0;
  angulo_deg = (pasosPorGrado != 0.0 && contadorAngulo != 0) ? (contadorAngulo / pasosPorGrado) : contadorAngulo;
}

// ======================= Control de motores =======================
void actualizarControlMotores() {
  // Secuencia de homing
  if (reiniciarX || reiniciarA) { controlarMotoresReset(); return; }

  // Flags de modo por eje
  bool manualX = (codigoModo & 0x01) != 0;
  bool manualA = (codigoModo & 0x02) != 0;

  // Calcular PID (el compute respeta el sample time)
  pidX.Compute();
  pidA.Compute();

  // Selección de comando por eje
  double cmdX = manualX ? energiaX : salidaPID_X;
  double cmdA = manualA ? energiaA : salidaPID_A;

  // Limitar por switches / límites físicos
  if (estadoLimiteX == HIGH && cmdX < 0) { cmdX = 0; contadorDistancia = 0; }
  if (posicionX_mm >= LIMITE_MAX_X_MM && cmdX > 0) cmdX = 0;

  if (estadoLimiteA == HIGH && cmdA < 0) { cmdA = 0; contadorAngulo = 0; }
  if (angulo_deg >= LIMITE_MAX_A_GRADOS && cmdA > 0) cmdA = 0;

  // Remapear energías
  cmdX = remapearEnergia((int)cmdX);
  cmdA = remapearEnergia((int)cmdA);

  // --- Bomba ---
  const int BOMBA_MAX = 255;
  int cmdBomba = 0;
  const float margenObjetivo = 0.05f;
  const bool objetivoPendiente = (volumenObjetivoML - volumenML) > margenObjetivo;
  const bool hayManual = (fabs(energiaBomba) > 1.0f);

  if (objetivoPendiente) {
    if (usarSensorFlujo) {
      cmdBomba = remapearEnergia(BOMBA_MAX);
      motorBomba.setSpeed(abs(cmdBomba));
      motorBomba.run(FORWARD);
    } else {
      const float restante = max(0.0f, volumenObjetivoML - volumenML);
      if (restante <= margenObjetivo) {
        cmdBomba = 0;
        motorBomba.setSpeed(0);
        motorBomba.run(RELEASE);
        tiempoInicioBombeo = 0;
        volumenObjetivoML = volumenML;
      } else {
        if (tiempoInicioBombeo == 0) tiempoInicioBombeo = millis();
        const unsigned long duracion_ms = (unsigned long)((restante / max(0.001f, caudalBombaMLs)) * 1000.0f);
        if (millis() - tiempoInicioBombeo < duracion_ms) {
          cmdBomba = remapearEnergia(BOMBA_MAX);
          motorBomba.setSpeed(abs(cmdBomba));
          motorBomba.run(FORWARD);
        } else {
          cmdBomba = 0;
          motorBomba.setSpeed(0);
          motorBomba.run(RELEASE);
          tiempoInicioBombeo = 0;
          volumenObjetivoML = volumenML;
        }
      }
    }
  } else if (hayManual) {
    cmdBomba = remapearEnergia((int)energiaBomba);
    motorBomba.setSpeed(abs(cmdBomba));
    motorBomba.run(cmdBomba > 0 ? FORWARD : BACKWARD);
  } else {
    cmdBomba = 0;
    motorBomba.setSpeed(0);
    motorBomba.run(RELEASE);
    tiempoInicioBombeo = 0;
  }

  // Aplicar a motores A y X
  motorAngulo.setSpeed(abs((int)cmdA));
  motorCorredera.setSpeed(abs((int)cmdX));
  motorAngulo.run(cmdA > 0 ? FORWARD : BACKWARD);
  motorCorredera.run(cmdX > 0 ? FORWARD : BACKWARD);
}

void controlarMotoresReset() {
  // Durante homing, forzamos dirección hacia los límites mínimos
  if (reiniciarX) {
    if (estadoLimiteX == LOW) energiaX = -200;  // hacia atrás
    else { energiaX = 0; reiniciarX = false; contadorDistancia = 0; motorCorredera.run(RELEASE); }
  }
  if (reiniciarA) {
    if (estadoLimiteA == LOW) energiaA = -200;
    else { energiaA = 0; reiniciarA = false; contadorAngulo = 0; motorAngulo.run(RELEASE); }
  }

  // Aplicar energías de reset
  int cmdX = remapearEnergia((int)energiaX);
  int cmdA = remapearEnergia((int)energiaA);
  motorCorredera.setSpeed(abs(cmdX)); motorCorredera.run(cmdX > 0 ? FORWARD : BACKWARD);
  motorAngulo.setSpeed(abs(cmdA));    motorAngulo.run(cmdA > 0 ? FORWARD : BACKWARD);
}

// ======================= I/O Serial =======================
void enviarDatos() {
  unsigned long ahora = millis();
  if (ahora - instanteEnvioAnterior < INTERVALO_ENVIO_MS) return;
  instanteEnvioAnterior = ahora;

  // Comandos aplicados (aprox) para reportar
  bool manualX = (codigoModo & 0x01) != 0;
  bool manualA = (codigoModo & 0x02) != 0;
  double cmdX = manualX ? energiaX : salidaPID_X;
  double cmdA = manualA ? energiaA : salidaPID_A;
  const float margenObjetivo = 0.05f;
  int    cmdB = 0;
  const bool objetivoPendiente = (volumenObjetivoML - volumenML) > margenObjetivo;
  const bool hayManual = (fabs(energiaBomba) > 1.0f);
  if (objetivoPendiente) cmdB = 255;
  else if (hayManual)    cmdB = remapearEnergia((int)energiaBomba);
  else                   cmdB = 0;

  // Reportar Z en mm
  float z_mm = (180.0f - z_current_deg) * z_mm_per_deg;
  String data = String('<') +
    String(posicionX_mm, 2) + "," +     // 0
    String(angulo_deg, 2) + "," +       // 1
    String((float)cmdB, 2) + "," +      // 2  (valor bomba aplicado)
    String(volumenML, 2) + "," +        // 3  (ml acumulados)
    String(estadoLimiteX) + "," +       // 4
    String(estadoLimiteA) + "," +       // 5
    String(reiniciarX ? 1 : 0) + "," +  // 6
    String(reiniciarA ? 1 : 0) + "," +  // 7
    String((float)cmdX, 2) + "," +      // 8
    String((float)cmdA, 2) + "," +      // 9
    String((float)cmdB, 2) + "," +      // 10
    String(codigoModo) + "," +          // 11
    String(kpX, 2) + "," +              // 12
    String(kiX, 2) + "," +              // 13
    String(kdX, 2) + "," +              // 14
    String(kpA, 2) + "," +              // 15
    String(kiA, 2) + "," +              // 16
    String(kdA, 2) + "," +              // 17
    String(pasosPorMM, 2) + "," +       // 18
    String(pasosPorGrado, 2) + "," +    // 19
    String(factorCalibracionFlujo, 2) + "," + // 20
    String(z_mm, 2) +                    // 21: z_mm
    String('>');
  Serial.println(data);
}

void recibirDatos() {
  if (!Serial.available()) return;
  String comando = Serial.readStringUntil('\n');
  procesarComando(comando);
}

void procesarComando(String command) {
  // dividir en tokens por coma (permitir >20 valores)
  const int MAXTOK = 32;
  String vals[MAXTOK];
  int n = 0;
  while (command.length() && n < MAXTOK) {
    int i = command.indexOf(',');
    if (i < 0) { vals[n++] = command; break; }
    vals[n++] = command.substring(0, i);
    command = command.substring(i + 1);
  }

  if (n < 20) {
    Serial.println("Error: cantidad de datos incorrecta.");
    return;
  }

  // ========== Mapeo 1:1 con Python (primeros 20) ==========
  uint8_t modoRx           = (uint8_t)vals[0].toInt();
  double energiaA_rx       = vals[1].toInt();
  double energiaX_rx       = vals[2].toInt();
  double energiaBomba_rx   = vals[3].toInt();
  double setpointX_mm_rx   = vals[4].toFloat();
  double setpointA_deg_rx  = vals[5].toFloat();
  double volumenObj_rx     = vals[6].toFloat();
  double kpX_rx            = vals[7].toFloat();
  double kiX_rx            = vals[8].toFloat();
  double kdX_rx            = vals[9].toFloat();
  double kpA_rx            = vals[10].toFloat();
  double kiA_rx            = vals[11].toFloat();
  double kdA_rx            = vals[12].toFloat();
  int resetVol_rx          = vals[13].toInt();
  bool resetXFlag          = (vals[14].toInt() == 1);
  bool resetAFlag          = (vals[15].toInt() == 1);
  float nuevosPasosMM      = vals[16].toFloat();
  float nuevosPasosGrado   = vals[17].toFloat();
  bool usarSensorFlujo_rx  = (vals[18].toInt() == 1);
  float caudalBomba_rx     = vals[19].toFloat();

  // Aplicar básicos
  codigoModo = modoRx;
  energiaA   = energiaA_rx;
  energiaX   = energiaX_rx;
  energiaBomba = energiaBomba_rx;
  setpointX_mm = setpointX_mm_rx;
  setpointA_deg = setpointA_deg_rx;
  float objetivoAnterior = volumenObjetivoML;
  volumenObjetivoML = volumenObj_rx;
  kpX = kpX_rx; kiX = kiX_rx; kdX = kdX_rx;
  kpA = kpA_rx; kiA = kiA_rx; kdA = kdA_rx;
  pidX.SetTunings(kpX, kiX, kdX);
  pidA.SetTunings(kpA, kiA, kdA);
  if (nuevosPasosMM != 0)    pasosPorMM = nuevosPasosMM;
  if (nuevosPasosGrado != 0) pasosPorGrado = nuevosPasosGrado;
  usarSensorFlujo = usarSensorFlujo_rx;
  caudalBombaMLs  = caudalBomba_rx;
  if (fabs(volumenObjetivoML - objetivoAnterior) > 0.01f) {
    tiempoInicioBombeo = 0;
    if (volumenObjetivoML <= volumenML) {
      volumenObjetivoML = volumenML;
    }
  }

  // Resets
  if (resetXFlag) reiniciarX = true;
  if (resetAFlag) reiniciarA = true;

  if (resetVol_rx == 1) {
    resetVolumen = 0;
    if (medidorFlujo) medidorFlujo->reset();
    volumenML = 0.0;
    tiempoInicioBombeo = 0;
  }

  // ========== Extras opcionales: servo Z ==========
  // Índices: 20=servoZ_deg, 21=servoZ_speed_deg_s, 22=setpointZ_mm, 23=z_mm_per_deg
  if (n > 21) {
    double v = vals[21].toFloat();
    if (!isnan(v) && v >= 0.0) z_speed_deg_s = v;
  }
  if (n > 23) {
    double s = vals[23].toFloat();
    if (!isnan(s) && s > 0.0001) z_mm_per_deg = s;
  }
  bool applied_mm = false;
  if (n > 22) {
    double zmm = vals[22].toFloat();
    if (!isnan(zmm)) {
      double deg = 180.0 - (zmm / (z_mm_per_deg <= 0.0001 ? 1.0 : z_mm_per_deg));
      z_target_deg = clampf(deg, SERVO_MIN_DEG, SERVO_MAX_DEG);
      applied_mm = true;
    }
  }
  if (!applied_mm && n > 20) {
    double d = vals[20].toFloat();
    if (!isnan(d)) z_target_deg = clampf(d, SERVO_MIN_DEG, SERVO_MAX_DEG);
  }
}
// (Se eliminó un bloque duplicado de definición de Servo para evitar redefiniciones)
