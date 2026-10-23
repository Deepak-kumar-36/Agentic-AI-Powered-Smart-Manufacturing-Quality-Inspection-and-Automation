#include <Arduino.h>

// GPIO definitions matching physical tested breadboard wiring:
// Red FAIL LED: GPIO 5 (D5)
// Green PASS LED: GPIO 4 (D4)
// IR Sensor OUT: GPIO 23 (D23)
constexpr uint8_t RED_LED_GPIO = 5;
constexpr uint8_t GREEN_LED_GPIO = 4;
constexpr uint8_t IR_SENSOR_GPIO = 23;

// Common reflective IR modules assert LOW when an object is detected.
// LED polarity is active HIGH (HIGH turns LED on).
constexpr uint8_t IR_SENSOR_ACTIVE_LEVEL = LOW;
constexpr uint8_t LED_ON_LEVEL = HIGH;
constexpr uint8_t LED_OFF_LEVEL = (LED_ON_LEVEL == HIGH) ? LOW : HIGH;

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr size_t MAX_LINE_BYTES = 1024;
constexpr size_t MAX_ID_BYTES = 64;
constexpr uint32_t SENSOR_DEBOUNCE_MS = 40;
constexpr uint32_t HEARTBEAT_TIMEOUT_MS = 5000;
constexpr uint32_t STARTUP_SAFE_MS = 1000;
constexpr uint32_t SENSOR_REPORT_INTERVAL_MS = 1000;
constexpr const char *FIRMWARE_VERSION = "1.0.0";

enum class Outcome : uint8_t { Unverified, Pass, Fail };

struct SensorState {
  bool rawActive = false;
  bool stableActive = false;
  uint32_t changedAt = 0;
  uint32_t sequence = 0;
  uint32_t lastReportAt = 0;
};

char lineBuffer[MAX_LINE_BYTES + 1];
size_t lineLength = 0;
bool discardingOversizedLine = false;
uint32_t lastHeartbeatAt = 0;
uint32_t bootStartedAt = 0;
Outcome outcome = Outcome::Unverified;
SensorState sensor;

void setIndicators(bool red, bool green) {
  digitalWrite(RED_LED_GPIO, red ? LED_ON_LEVEL : LED_OFF_LEVEL);
  digitalWrite(GREEN_LED_GPIO, green ? LED_ON_LEVEL : LED_OFF_LEVEL);
}

void safeIndicatorsOff() {
  setIndicators(false, false);
}

bool linkStale(uint32_t now) {
  return static_cast<uint32_t>(now - lastHeartbeatAt) > HEARTBEAT_TIMEOUT_MS;
}

const char *outcomeName() {
  switch (outcome) {
    case Outcome::Pass: return "PASS";
    case Outcome::Fail: return "FAIL";
    default: return "UNVERIFIED";
  }
}

void writeJson(const char *json) {
  // Never block the control loop when a USB/UART peer disappears. A dropped
  // status line is safe; the next status/event can be emitted later.
  const size_t length = strlen(json);
  if (length == 0 || Serial.availableForWrite() < static_cast<int>(length + 1)) return;
  Serial.write(reinterpret_cast<const uint8_t *>(json), length);
  Serial.write('\n');
}

void emitError(const char *code, const char *commandId = nullptr) {
  char json[256];
  if (commandId != nullptr && commandId[0] != '\0') {
    snprintf(json, sizeof(json),
             "{\"schema_version\":1,\"type\":\"error\",\"error_code\":\"%s\",\"command_id\":\"%s\"}",
             code, commandId);
  } else {
    snprintf(json, sizeof(json),
             "{\"schema_version\":1,\"type\":\"error\",\"error_code\":\"%s\"}", code);
  }
  writeJson(json);
}

bool isJsonObject(const char *json) {
  const size_t length = strlen(json);
  if (length < 2 || json[0] != '{' || json[length - 1] != '}') return false;
  for (size_t i = 0; i < length; ++i) {
    if (static_cast<unsigned char>(json[i]) < 0x20) return false;
  }
  return true;
}

bool readStringField(const char *json, const char *field, char *value, size_t valueSize) {
  char key[80];
  snprintf(key, sizeof(key), "\"%s\"", field);
  const char *start = strstr(json, key);
  if (start == nullptr) return false;
  start = strchr(start + strlen(key), ':');
  if (start == nullptr) return false;
  ++start;
  while (*start == ' ' || *start == '\t') ++start;
  if (*start != '\"') return false;
  ++start;
  size_t length = 0;
  while (start[length] != '\0' && start[length] != '\"') {
    if (start[length] == '\\' || static_cast<unsigned char>(start[length]) < 0x20) return false;
    if (length + 1 >= valueSize) return false;
    ++length;
  }
  if (start[length] != '\"') return false;
  memcpy(value, start, length);
  value[length] = '\0';
  return true;
}

bool readSchemaVersion(const char *json) {
  const char *field = strstr(json, "\"schema_version\"");
  if (field == nullptr) return false;
  field = strchr(field, ':');
  if (field == nullptr) return false;
  ++field;
  while (*field == ' ' || *field == '\t') ++field;
  return *field == '1' && (field[1] == ',' || field[1] == '}' || field[1] == ' ' || field[1] == '\t');
}

void emitStatus(uint32_t now, const char *type) {
  char json[440];
  snprintf(json, sizeof(json),
           "{\"schema_version\":1,\"type\":\"%s\",\"firmware_version\":\"%s\",\"state\":\"%s\",\"outcome\":\"%s\",\"sensor_active\":%s,\"active\":%s,\"sensor_raw_active\":%s,\"sensor_sequence\":%lu,\"link_stale\":%s,\"uptime_ms\":%lu}",
           type, FIRMWARE_VERSION, linkStale(now) ? "STALE" : "READY", outcomeName(),
           sensor.stableActive ? "true" : "false", sensor.stableActive ? "true" : "false", sensor.rawActive ? "true" : "false",
           static_cast<unsigned long>(sensor.sequence), linkStale(now) ? "true" : "false",
           static_cast<unsigned long>(now - bootStartedAt));
  writeJson(json);
}

void applyOutcome(Outcome requested, uint32_t now) {
  outcome = requested;
  if (requested == Outcome::Pass) setIndicators(false, true);
  else if (requested == Outcome::Fail) setIndicators(true, false);
  else safeIndicatorsOff();
  emitStatus(now, "inspection.status");
}

void handleLine(const char *json, uint32_t now) {
  if (!isJsonObject(json)) { emitError("ERR_BAD_JSON"); return; }
  if (!readSchemaVersion(json)) { emitError("ERR_SCHEMA_VERSION"); return; }

  char type[40];
  if (!readStringField(json, "type", type, sizeof(type))) { emitError("ERR_BAD_JSON"); return; }
  if (strcmp(type, "heartbeat") == 0) {
    lastHeartbeatAt = now;
    emitStatus(now, "controller.status");
    return;
  }
  if (strcmp(type, "controller.status.request") == 0 || strcmp(type, "sensor.status.request") == 0) {
    emitStatus(now, "controller.status");
    return;
  }
  if (strcmp(type, "inspection.disposition") != 0) { emitError("ERR_UNKNOWN_COMMAND"); return; }

  char commandId[MAX_ID_BYTES] = "";
  const bool hasCommandId = readStringField(json, "command_id", commandId, sizeof(commandId));
  char decision[16] = "";
  char inspectionId[MAX_ID_BYTES] = "";
  const bool hasDecision = readStringField(json, "decision", decision, sizeof(decision));
  const bool hasInspectionId = readStringField(json, "inspection_id", inspectionId, sizeof(inspectionId));

  if (!hasCommandId || !hasDecision || !hasInspectionId) {
    emitError("ERR_FIELD_INVALID", hasCommandId ? commandId : nullptr);
    return;
  }

  // A valid disposition is link activity, keeping the controller connection fresh.
  lastHeartbeatAt = now;
  Outcome requested = Outcome::Unverified;
  if (strcmp(decision, "PASS") == 0) requested = Outcome::Pass;
  else if (strcmp(decision, "FAIL") == 0) requested = Outcome::Fail;
  else if (strcmp(decision, "UNVERIFIED") == 0) requested = Outcome::Unverified;
  else {
    char errAck[320];
    snprintf(errAck, sizeof(errAck),
             "{\"schema_version\":1,\"type\":\"command.ack\",\"command_id\":\"%s\",\"inspection_id\":\"%s\",\"status\":\"REJECTED\",\"ok\":false,\"error_code\":\"ERR_FIELD_INVALID\"}",
             commandId, inspectionId);
    writeJson(errAck);
    return;
  }

  applyOutcome(requested, now);
  char ack[320];
  snprintf(ack, sizeof(ack),
           "{\"schema_version\":1,\"type\":\"command.ack\",\"command_id\":\"%s\",\"inspection_id\":\"%s\",\"status\":\"ACCEPTED\",\"ok\":true,\"outcome\":\"%s\",\"controller_state\":\"%s\"}",
           commandId, inspectionId, outcomeName(), requested == Outcome::Unverified ? "UNVERIFIED_HOLD" : "INDICATOR_ONLY");
  writeJson(ack);
}

void readSerial(uint32_t now) {
  while (Serial.available() > 0) {
    const char character = static_cast<char>(Serial.read());
    if (character == '\n') {
      if (discardingOversizedLine) emitError("ERR_LINE_TOO_LONG");
      else if (lineLength == 0) emitError("ERR_BAD_JSON");
      else { lineBuffer[lineLength] = '\0'; handleLine(lineBuffer, now); }
      lineLength = 0;
      discardingOversizedLine = false;
    } else if (character != '\r') {
      if (discardingOversizedLine) continue;
      if (lineLength >= MAX_LINE_BYTES) { lineLength = 0; discardingOversizedLine = true; }
      else lineBuffer[lineLength++] = character;
    }
  }
}

void updateSensor(uint32_t now) {
  const bool rawActive = digitalRead(IR_SENSOR_GPIO) == IR_SENSOR_ACTIVE_LEVEL;
  if (rawActive != sensor.rawActive) {
    sensor.rawActive = rawActive;
    sensor.changedAt = now;
  }
  if (sensor.stableActive != sensor.rawActive && static_cast<uint32_t>(now - sensor.changedAt) >= SENSOR_DEBOUNCE_MS) {
    sensor.stableActive = sensor.rawActive;
    ++sensor.sequence;
    char json[260];
    snprintf(json, sizeof(json),
             "{\"schema_version\":1,\"type\":\"sensor.state\",\"sensor\":\"ir_presence\",\"sensor_active\":%s,\"active\":%s,\"raw_active\":%s,\"sequence\":%lu}",
             sensor.stableActive ? "true" : "false", sensor.stableActive ? "true" : "false", sensor.rawActive ? "true" : "false",
             static_cast<unsigned long>(sensor.sequence));
    writeJson(json);
  }
  if (static_cast<uint32_t>(now - sensor.lastReportAt) >= SENSOR_REPORT_INTERVAL_MS) {
    sensor.lastReportAt = now;
    emitStatus(now, "sensor.status");
  }
}

void setup() {
  pinMode(RED_LED_GPIO, OUTPUT);
  pinMode(GREEN_LED_GPIO, OUTPUT);
  safeIndicatorsOff(); // First observable output is safe, before Serial starts.
  pinMode(IR_SENSOR_GPIO, INPUT_PULLUP); // GPIO 23 input with pullup keeps stable HIGH when clear.
  Serial.begin(SERIAL_BAUD);
  bootStartedAt = millis();
  lastHeartbeatAt = bootStartedAt;
  sensor.rawActive = digitalRead(IR_SENSOR_GPIO) == IR_SENSOR_ACTIVE_LEVEL;
  sensor.stableActive = sensor.rawActive;
  sensor.changedAt = bootStartedAt;
  emitStatus(bootStartedAt, "hello");
}

void loop() {
  const uint32_t now = millis();
  readSerial(now);
  updateSensor(now);
  if (static_cast<uint32_t>(now - bootStartedAt) < STARTUP_SAFE_MS || linkStale(now)) {
    if (outcome != Outcome::Unverified) {
      outcome = Outcome::Unverified;
      emitStatus(now, "inspection.status");
    }
    safeIndicatorsOff();
  }
  delay(1);
}

