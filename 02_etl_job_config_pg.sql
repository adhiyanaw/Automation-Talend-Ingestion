-- etl_job_config (PostgreSQL) - kolom disamakan dengan DM_ANALYTICS.ETL_JOB_CONFIG milik felix
-- + kolom tambahan khusus ingestion ke S3 (bagian "EXTRA"). Jalankan sekali.

CREATE TABLE IF NOT EXISTS etl_job_config (
  job_code             varchar(100) NOT NULL,
  is_active            varchar(1)   NOT NULL DEFAULT 'Y',
  category_module      varchar(100) NOT NULL DEFAULT 'TALEND_JOB_TEMPLATE',
  target_job_template  varchar(200),
  source_db_type       varchar(20)  NOT NULL DEFAULT 'POSTGRESQL',
  source_conn_category varchar(100),
  source_schema        varchar(50)  NOT NULL,
  source_object        varchar(200) NOT NULL,
  source_sql           varchar(4000),
  target_schema        varchar(50)  NOT NULL,
  target_table         varchar(200) NOT NULL,
  layer                varchar(20)  NOT NULL DEFAULT 'BRONZE',
  load_strategy        varchar(20)  DEFAULT 'INSERT',
  description          varchar(500),
  project_name         varchar(200) NOT NULL,
  version              varchar(20)  NOT NULL,
  -- EXTRA (ingestion ke S3, dipakai mulai 0.3)
  s3_bucket            varchar(200),
  s3_prefix            varchar(300),
  file_name            varchar(200),
  file_separator       varchar(5)   DEFAULT '|',
  CONSTRAINT pk_etl_job_config PRIMARY KEY (job_code)
);

-- pindahkan baris contoh dari cfg_job_config (jika masih ada)
INSERT INTO etl_job_config
 (job_code, is_active, source_schema, source_object, source_sql,
  target_schema, target_table, project_name, version, description)
VALUES
 ('LocalIngestionTable','Y','public','transaksi_penjualan_dummy',
  'SELECT * FROM public.transaksi_penjualan_dummy',
  'public','transaksi_penjualan_dummy_out','LocalIngestionTable','0.2',
  'Template lokal: PostgreSQL ke PostgreSQL')
ON CONFLICT (job_code) DO NOTHING;
-- catatan: SELECT * hanya untuk lab; di customer kolom ditulis satu per satu (aturan felix).
