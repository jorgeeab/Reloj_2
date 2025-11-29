// Opuno Pump — Arduino sketch (serial-controlled)
// Protocolo compatible con Reloj/Opuno servers (24 valores TX → 22 RX)
// - Usa bit 3 (valor 8) del campo codigoModo como trigger EXECUTE
// - Permite enviar primero objetivos (volumen y caudal) y luego ejecutar con execute=1

#include <Arduino.h>

// ======================= Config IO =======================
const uint8_t PUMP_PIN = 9;       // PWM (MOSFET o driver)
const bool ACTIVE_HIGH = true;    // HIGH enciende

// ======================= Estado ==========================
// Calibraciones y setpoints
float pasosPorMM = 1.0f;
float pasosPorGrado = 1.0f;
float factorCalibracionFlujo = 1.0f; // reservado
float caudalBombaMLs = 50.0f;        // ml/s @255

// Flujo/volumen
float caudalMLs = 0.0f;              // ml/s estimado
float volumenML = 0.0f;              // ml acumulados
float volumenObjetivoML = 0.0f;      // objetivo ml
bool  usarSensorFlujo = false;       // en esta versión no hay sensor; estimación por energía

// Energías y modo
double energiaBomba = 0.0;           // -255..255
uint8_t codigoModo = 0;              // bit3 = EXECUTE

// Timing
unsigned long lastMs = 0;

static inline float clampf(float v, float lo, float hi){ return (v<lo?lo:(v>hi?hi:v)); }

// ======================= Pump I/O ========================
void pumpWrite(uint8_t pwm){
  if(ACTIVE_HIGH){ analogWrite(PUMP_PIN, pwm); }
  else{ analogWrite(PUMP_PIN, 255 - pwm); }
}

// ======================= Serial helpers ==================
void enviarOBS(float cmdX, float cmdA, float cmdB){
  // 22 valores — rellenamos con ceros donde no aplica
  String s = "<";
  s += String(0.0f, 2) + ",";                // 0 posX_mm
  s += String(0.0f, 2) + ",";                // 1 angulo_deg
  s += String((float)cmdB, 2) + ",";         // 2 valorBombaAplicado
  s += String(volumenML, 2) + ",";            // 3 volumenML
  s += String(0) + ",";                       // 4 limX
  s += String(0) + ",";                       // 5 limA
  s += String(0) + ",";                       // 6 homingX
  s += String(0) + ",";                       // 7 homingA
  s += String((float)cmdX, 2) + ",";          // 8 cmdX_aplicado
  s += String((float)cmdA, 2) + ",";          // 9 cmdA_aplicado
  s += String((float)cmdB, 2) + ",";          // 10 cmdBomba_aplicado
  s += String(codigoModo) + ",";              // 11 codigoModo
  s += String(0.0f, 2) + ",";                 // 12 kpX
  s += String(0.0f, 2) + ",";                 // 13 kiX
  s += String(0.0f, 2) + ",";                 // 14 kdX
  s += String(0.0f, 2) + ",";                 // 15 kpA
  s += String(0.0f, 2) + ",";                 // 16 kiA
  s += String(0.0f, 2) + ",";                 // 17 kdA
  s += String(pasosPorMM, 2) + ",";           // 18 pasosPorMM
  s += String(pasosPorGrado, 2) + ",";        // 19 pasosPorGrado
  s += String(factorCalibracionFlujo, 2) + ",";// 20 factor flujo
  s += String(0.0f, 2);                        // 21 z_mm
  s += ">";
  Serial.println(s);
}

void procesarLinea(String command){
  // split por comas, aceptar hasta 32 tokens
  const int MAXTOK=32; String v[MAXTOK]; int n=0;
  while(command.length() && n<MAXTOK){
    int i=command.indexOf(',');
    if(i<0){ v[n++]=command; break; }
    v[n++]=command.substring(0,i); command=command.substring(i+1);
  }
  if(n<20) return;

  uint8_t modoRx           = (uint8_t)v[0].toInt();
  double energiaA_rx       = v[1].toInt(); (void)energiaA_rx;
  double energiaX_rx       = v[2].toInt(); (void)energiaX_rx;
  double energiaBomba_rx   = v[3].toInt();
  double setpointX_mm_rx   = v[4].toFloat(); (void)setpointX_mm_rx;
  double setpointA_deg_rx  = v[5].toFloat(); (void)setpointA_deg_rx;
  double volumenObj_rx     = v[6].toFloat();
  // 7..12 PID — ignorados aquí
  int resetVol_rx          = v[13].toInt();
  bool resetXFlag          = (v[14].toInt()==1); (void)resetXFlag;
  bool resetAFlag          = (v[15].toInt()==1); (void)resetAFlag;
  float nuevosPasosMM      = v[16].toFloat(); if(nuevosPasosMM!=0) pasosPorMM=nuevosPasosMM;
  float nuevosPasosGrado   = v[17].toFloat(); if(nuevosPasosGrado!=0) pasosPorGrado=nuevosPasosGrado;
  bool usarSensorFlujo_rx  = (v[18].toInt()==1);
  float caudalBomba_rx     = v[19].toFloat();

  codigoModo = modoRx;               // incluye trigger bit3
  energiaBomba = energiaBomba_rx;    // usado solo si no hay sensor
  volumenObjetivoML = max(0.0f, (float)volumenObj_rx);
  usarSensorFlujo = usarSensorFlujo_rx;
  if(caudalBomba_rx>0.0f) caudalBombaMLs = caudalBomba_rx;
  if(resetVol_rx==1){ volumenML=0.0f; }
}

void setup(){
  Serial.begin(115200);
  pinMode(PUMP_PIN, OUTPUT);
  pumpWrite(0);
  lastMs = millis();
}

void loop(){
  while(Serial.available()>0){
    String line = Serial.readStringUntil('\n');
    line.trim(); if(line.length()) procesarLinea(line);
  }

  unsigned long now = millis();
  float dt = (lastMs==0)?0.0f: (now - lastMs)/1000.0f; lastMs = now;

  const float margen = 0.05f;
  const bool objetivoPendiente = (volumenObjetivoML - volumenML) > margen;
  const bool execOn = (codigoModo & 0x08) != 0; // bit3 EXECUTE

  uint8_t pumpPwm = 0;
  if(objetivoPendiente && execOn){
    // Sin sensor: estimar por energía → caudal
    float frac = clampf((float)fabs(energiaBomba)/255.0f, 0.0f, 1.0f);
    caudalMLs = caudalBombaMLs * frac;
    volumenML += caudalMLs * dt;
    pumpPwm = (uint8_t)clampf((float)fabs(energiaBomba), 0.0f, 255.0f);
    if(volumenML >= volumenObjetivoML - margen){ pumpPwm=0; }
  }else{
    caudalMLs = 0.0f;
    pumpPwm = 0;
  }

  pumpWrite(pumpPwm);
  enviarOBS(0.0f, 0.0f, (float)pumpPwm);
}

