// Base Pump — Arduino sketch (mínimo)
// Protocolo serie compatible (24 TX → 22 RX), con trigger EXECUTE en bit3 de codigoModo

#include <Arduino.h>

const uint8_t PUMP_PIN = 9;  // PWM
const bool ACTIVE_HIGH = true;

float caudalBombaMLs = 50.0f; // ml/s @255
float volumenObjetivoML = 0.0f;
float volumenML = 0.0f;
double energiaBomba = 0.0;    // -255..255
uint8_t codigoModo = 0;       // bit3 = EXECUTE
bool usarSensorFlujo = false;
unsigned long lastMs = 0;

static inline float clampf(float v,float lo,float hi){ return v<lo?lo:(v>hi?hi:v); }
void pumpWrite(uint8_t pwm){ analogWrite(PUMP_PIN, ACTIVE_HIGH? pwm : 255-pwm); }

void enviarOBS(float cmdB){
  String s = "<";
  s += String(0.0f,2) + ",";        // 0
  s += String(0.0f,2) + ",";        // 1
  s += String(cmdB,2) + ",";        // 2 valorBombaAplicado
  s += String(volumenML,2) + ",";    // 3 volumenML
  s += String(0) + "," + String(0) + "," + String(0) + "," + String(0) + ","; // 4..7
  s += String(0.0f,2) + "," + String(0.0f,2) + ","; // 8..9
  s += String(cmdB,2) + ",";        // 10
  s += String(codigoModo) + ",";    // 11
  s += String(0.0f,2) + "," + String(0.0f,2) + "," + String(0.0f,2) + ","; // 12..14
  s += String(0.0f,2) + "," + String(0.0f,2) + "," + String(0.0f,2) + ","; // 15..17
  s += String(1.0f,2) + "," + String(1.0f,2) + "," + String(1.0f,2) + ",";  // 18..20
  s += String(0.0f,2);                 // 21 z_mm
  s += ">";
  Serial.println(s);
}

void procesar(String ln){
  const int N=32; String v[N]; int n=0;
  while(ln.length() && n<N){ int i=ln.indexOf(','); if(i<0){ v[n++]=ln; break; } v[n++]=ln.substring(0,i); ln=ln.substring(i+1);}  
  if(n<20) return;
  codigoModo = (uint8_t)v[0].toInt();
  energiaBomba = v[3].toInt();
  volumenObjetivoML = max(0.0f, v[6].toFloat());
  usarSensorFlujo = (v[18].toInt()==1);
  float cmax = v[19].toFloat(); if(cmax>0) caudalBombaMLs=cmax;
  if(v[13].toInt()==1){ volumenML=0.0f; }
}

void setup(){ Serial.begin(115200); pinMode(PUMP_PIN, OUTPUT); pumpWrite(0); lastMs=millis(); }

void loop(){
  while(Serial.available()>0){ String l=Serial.readStringUntil('\n'); l.trim(); if(l.length()) procesar(l); }
  unsigned long now=millis(); float dt=(lastMs==0)?0.0f:(now-lastMs)/1000.0f; lastMs=now;
  const bool execOn = (codigoModo & 0x08)!=0; const float margen=0.05f; const bool pend=(volumenObjetivoML - volumenML)>margen;
  uint8_t pwm=0; if(pend && execOn){ float frac=clampf((float)fabs(energiaBomba)/255.0f,0.0f,1.0f); volumenML += (caudalBombaMLs*frac)*dt; pwm=(uint8_t)clampf((float)fabs(energiaBomba),0.0f,255.0f); if(volumenML>=volumenObjetivoML-margen){ pwm=0; } }
  pumpWrite(pwm); enviarOBS((float)pwm);
}

