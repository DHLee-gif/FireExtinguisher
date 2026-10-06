CREATE DATABASE IF NOT EXISTS firecar
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE firecar;

CREATE TABLE IF NOT EXISTS admin (
    admin_id      INT AUTO_INCREMENT PRIMARY KEY,
    login_id      VARCHAR(30)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    name          VARCHAR(30)  NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at    DATETIME
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS device (
    device_id     INT PRIMARY KEY,
    name          VARCHAR(50) NOT NULL,
    battery_level FLOAT,
    last_seen     DATETIME
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fire_log (
    event_id     INT AUTO_INCREMENT PRIMARY KEY,
    device_id    INT NOT NULL,
    temperature  FLOAT,
    vision_score FLOAT,
    status       ENUM('detected','spraying','extinguished','failed') NOT NULL DEFAULT 'detected',
    detected_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at    DATETIME,
    INDEX idx_fire_log_detected_at (detected_at),
    CONSTRAINT fk_fire_log_device FOREIGN KEY (device_id) REFERENCES device (device_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fire_image (
    image_id  INT AUTO_INCREMENT PRIMARY KEY,
    event_id  INT NOT NULL,
    img_type  ENUM('before','after') NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    taken_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_fire_image_event FOREIGN KEY (event_id)
        REFERENCES fire_log (event_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS spray_log (
    spray_id    INT AUTO_INCREMENT PRIMARY KEY,
    event_id    INT NOT NULL,
    duration_ms INT,
    temp_after  FLOAT,
    started_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_spray_log_event FOREIGN KEY (event_id)
        REFERENCES fire_log (event_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS device_status_log (
    log_id      INT AUTO_INCREMENT PRIMARY KEY,
    device_id   INT NOT NULL,
    level       ENUM('normal','warning','error') NOT NULL,
    code        VARCHAR(30),
    message     VARCHAR(100),
    logged_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    INDEX idx_device_status_log_logged_at (logged_at),
    CONSTRAINT fk_device_status_log_device FOREIGN KEY (device_id) REFERENCES device (device_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS water_log (
    log_id      INT AUTO_INCREMENT PRIMARY KEY,
    device_id   INT NOT NULL,
    water_level FLOAT,
    action      ENUM('low','homing','refilled','homing_failed'),
    logged_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_water_log_logged_at (logged_at),
    CONSTRAINT fk_water_log_device FOREIGN KEY (device_id) REFERENCES device (device_id)
) ENGINE=InnoDB;
