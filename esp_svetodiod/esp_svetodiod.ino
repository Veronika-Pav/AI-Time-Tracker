#define LED_PIN 2  // GPIO2 (встроенный светодиод)

void setup() {
  Serial.begin(9600);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // HIGH - выключен (инверсная логика)
  
  // Сигнал, что ESP готов
  delay(500);
  Serial.println("ESP-12E готов к работе");
  
  // Мигаем 2 раза при запуске (проверка)
  blink(2);
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    
    if (command == "BLINK") {
      blink(5);
      Serial.println("LED мигнул 5 раз");
    }
    else if (command == "ON") {
      digitalWrite(LED_PIN, LOW);   // LOW - включён (инверсная логика)
      Serial.println("LED включен");
    }
    else if (command == "OFF") {
      digitalWrite(LED_PIN, HIGH);  // HIGH - выключен
      Serial.println("LED выключен");
    }
    else if (command == "TEST") {
      blink(3);
      Serial.println("Тест пройден");
    }
  }
}

void blink(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, LOW);   // Включить
    delay(200);
    digitalWrite(LED_PIN, HIGH);  // Выключить
    delay(200);
  }
}
