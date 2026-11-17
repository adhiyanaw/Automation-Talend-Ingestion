-- ============================================================
-- 01_cfg_job_config.sql  (PostgreSQL)
-- Tabel konfigurasi job ingestion (draf F2.3).
-- Dibuat di schema default (public) dengan awalan cfg_ supaya
-- tidak butuh izin CREATE SCHEMA. Aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS cfg_job_config (
    job_code        varchar(100) PRIMARY KEY,          -- kunci unik per job (mirip ETL_JOB_CONFIG)
    template        varchar(10)  NOT NULL,             -- A, B, C, atau SAMPLE
    active          boolean      NOT NULL DEFAULT true,

    source_conn     varchar(100),                      -- nama context group sumber (mis. LocalPostgres)
    source_schema   varchar(100),
    source_table    varchar(200),
    source_query    text,                              -- bila diisi, dipakai menggantikan source_table
    filter_column   varchar(100),                      -- kolom partisi (mis. dt_pr / report_date)
    filter_value    varchar(100),                      -- nilai filter; kosong = tanpa filter

    target_conn     varchar(100),                      -- koneksi target DB (uji DB ke DB)
    target_schema   varchar(100),
    target_table    varchar(200),

    file_name       varchar(200),                      -- untuk jalur ke S3 (nanti)
    file_separator  varchar(10)  DEFAULT ';',
    file_encoding   varchar(20)  DEFAULT 'UTF-8',
    s3_bucket       varchar(200),
    s3_prefix       varchar(300),

    child_job       varchar(200),                      -- job anak (menunggu rancangan DBX)
    notes           text,
    created_at      timestamp    NOT NULL DEFAULT now(),
    updated_at      timestamp    NOT NULL DEFAULT now()
);

COMMENT ON TABLE cfg_job_config IS 'Konfigurasi job ingestion per job_code (dibaca job saat berjalan)';

-- Data contoh: job uji LocalIngestionTable
-- CATATAN: target_table adalah ASUMSI; ganti sesuai tabel target yang kamu pakai.
INSERT INTO cfg_job_config
    (job_code, template, source_conn, source_schema, source_table,
     target_conn, target_schema, target_table, notes)
VALUES
    ('LocalIngestionTable', 'SAMPLE', 'LocalPostgres', 'public', 'transaksi_penjualan_dummy',
     'LocalPostgres', 'public', 'tgt_transaksi_penjualan_dummy',
     'Job uji alur Nexus/TAC; ingestion 1 tabel')
ON CONFLICT (job_code) DO NOTHING;

-- Cek hasil
SELECT job_code, template, active, source_table, target_table FROM cfg_job_config;
