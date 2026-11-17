# Talend push tool v1.0 (Nexus + TAC)

Alur: zip hasil **Build Job** Studio -> Nexus -> task di TAC -> jadwal cron -> (opsional) run.
Default **dry-run**: hanya mencetak apa yang akan dikirim. `--apply` = kirim sungguhan.

## Persiapan (sekali)
1. `pip install -r requirements.txt`
2. `copy config.example.yaml config.yaml` lalu isi `nexus.repository`, `defaults.execution_server`
3. `copy jobs.example.yaml jobs.yaml`
4. Di Studio: klik kanan job > **Build Job** > Archive type `.zip`, taruh di folder `builds\`
   (nama file bebas, isi path-nya di `build_zip`).
5. Kredensial lewat environment variable (PowerShell):
   `$env:TAC_USER="..."; $env:TAC_PASS="..."; $env:NEXUS_USER="..."; $env:NEXUS_PASS="..."`
   Kalau tidak diset, script bertanya saat `--apply`. Jangan simpan password di file.

## Pemakaian
```
python deploy.py                         # dry-run semua job aktif
python deploy.py --job ZZ_SAMPLE_PUSH --apply
python deploy.py --category SAMPLE --steps upload,task,trigger --apply
python deploy.py --job ZZ_SAMPLE_PUSH --steps run --apply   # jalankan task
```
Steps: `upload` (Nexus), `task` (buat task TAC), `trigger` (jadwal cron), `run`.

## Yang perlu diverifikasi saat uji lab (belum pernah jalan di server asli)
- Apakah TAC menerima artefak hasil upload ini (zip Build Job + pom otomatis) pada
  `associatePreGeneratedJob` dengan importType Nexus. Jika tidak, publish dari Studio
  dulu satu kali, lalu samakan `group_id` / struktur dengan hasilnya.
- Format respons `getTaskIdByName` (script membaca field `result`).
- Nama project: project di TAC harus sama persis dengan Studio (BSIM_LOCAL).
- Context parameter per environment (mis. `path_tempfile`) belum diatur oleh script ini.

Diuji dengan server tiruan lokal: `python tests/mock_test.py`.
