CREATE TABLE `User` (
  `userID` varchar(100) NOT NULL,
  `email` varchar(50) NOT NULL, 
  `firstName` varchar(50) NOT NULL, 
  `lastName` varchar(50) NOT NULL, 
  `password` varchar(60) NOT NULL,
  `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updatedAt` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `authenticated` BOOLEAN NOT NULL,
  UNIQUE(`userID`,`email`),
  PRIMARY KEY (`email`)
);

CREATE TABLE `Album` (
  `email` varchar(50) NOT NULL,
  `albumID` varchar(100) NOT NULL,
  `name` varchar(50) NOT NULL,
  `description` TEXT NOT NULL,
  `thumbnailURL` TEXT NOT NULL,
  `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`albumID`),
  FOREIGN KEY (`email`) REFERENCES `User`(`email`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE `Photo` (
  `photoID` varchar(100) NOT NULL,
  `albumID` varchar(100) NOT NULL,
  `title` TEXT,
  `description` TEXT,
  `tags` TEXT,
  `photoURL` TEXT NOT NULL,
  `EXIF` TEXT,
  `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updatedAt` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`photoID`),
  FOREIGN KEY (`albumID`) REFERENCES `Album` (`albumID`) ON DELETE CASCADE ON UPDATE CASCADE
);
