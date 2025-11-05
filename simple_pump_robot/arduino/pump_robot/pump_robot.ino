// Simple Pump Robot – Arduino sketch
// Controla una bomba con un pin digital (relevador o MOSFET)
// Protocolo serie:
//  - "RUN <ms>"  -> activa la bomba por <ms> milisegundos
//  - "STOP"      -> apaga la bomba

const int PUMP_PIN = 8;          // Cambia según tu cableado
const bool ACTIVE_HIGH = true;   // true si ON es HIGH; false si ON es LOW

unsigned long runUntilMs = 0;
String buff;

void pumpOn(){ digitalWrite(PUMP_PIN, ACTIVE_HIGH ? HIGH : LOW); }
void pumpOff(){ digitalWrite(PUMP_PIN, ACTIVE_HIGH ? LOW : HIGH); }

void setup(){
  pinMode(PUMP_PIN, OUTPUT);
  pumpOff();
  Serial.begin(115200);
}

void loop(){
  // Procesar comandos
  while(Serial.available() > 0){
    char c = Serial.read();
    if(c == '\n' || c == '\r'){
      buff.trim();
      if(buff.length() > 0){
        if(buff.startsWith("RUN ")){
          unsigned long ms = buff.substring(4).toInt();
          pumpOn();
          runUntilMs = millis() + ms;
          Serial.println("OK");
        }else if(buff == "STOP"){
          pumpOff();
          runUntilMs = 0;
          Serial.println("STOPPED");
        }else if(buff == "PING"){
          Serial.println("PONG");
        }
      }
      buff = "";
    }else{
      buff += c;
    }
  }

  // Apagar por tiempo
  if(runUntilMs > 0 && millis() >= runUntilMs){
    pumpOff();
    runUntilMs = 0;
    Serial.println("DONE");
  }
}

