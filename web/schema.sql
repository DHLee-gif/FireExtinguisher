CREATE DATABASE IF NOT EXISTS firecar
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE firecar;

CREATE TABLE IF NOT EXISTS admin (
    admin_id      INT AUTO_INCREMENT PRIMARY KEY,
    login_id      VARCHAR(30)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    name          VARCHAR(30)  NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS device (
    device_id INT PRIMARY KEY,
    name      VARCHAR(50),
    last_seen DATETIME
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fire_event (
    event_id     INT AUTO_INCREMENT PRIMARY KEY,
    detected_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    temperature  FLOAT,
    vision_score FLOAT,
    status       ENUM('detected','spraying','extinguished','failed') DEFAULT 'detected',
    closed_at    DATETIME,
    INDEX idx_fire_event_detected_at (detected_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fire_image (
    image_id  INT AUTO_INCREMENT PRIMARY KEY,
    event_id  INT NOT NULL,
    img_type  ENUM('before','after') NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    taken_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_fire_image_event FOREIGN KEY (event_id)
        REFERENCES fire_event (event_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS spray_log (
    spray_id    INT AUTO_INCREMENT PRIMARY KEY,
    event_id    INT NOT NULL,
    started_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration_ms INT,
    temp_after  FLOAT,
    CONSTRAINT fk_spray_log_event FOREIGN KEY (event_id)
        REFERENCES fire_event (event_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS status_log (
    log_id      INT AUTO_INCREMENT PRIMARY KEY,
    logged_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    level       ENUM('normal','warning','error') NOT NULL,
    code        VARCHAR(30),
    message     VARCHAR(100),
    resolved_at DATETIME
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS water_log (
    log_id      INT AUTO_INCREMENT PRIMARY KEY,
    logged_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    water_level FLOAT,
    action      ENUM('low','homing','refilled','homing_failed')
) ENGINE=InnoDB;
