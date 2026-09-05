-- Runs once on first container start. Creates the extension in the main DB
-- and a separate database for the test suite.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE DATABASE consensus_test;
\connect consensus_test
CREATE EXTENSION IF NOT EXISTS vector;
