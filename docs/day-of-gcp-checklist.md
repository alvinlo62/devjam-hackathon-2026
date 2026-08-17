# 比賽當天 GCP／GitHub 重新設定清單

> 這套 infra（Cloud Run、Cloud SQL、CI/CD）已經在測試專案上完整驗證過一次
> （見 commit history）。這份清單只是把「換帳號後要重新填的東西」列出來，
> **邏輯不用重新設計，照著填值就好。**
>
> 用 GitHub 的「Use this template」生出新 repo 後，程式碼跟 workflow 邏輯會
> 一起帶過去，但 repo 的 Secrets／Variables／Environments 設定不會，這份清單
> 就是在補那一段。

---

## 0. 拿到比賽方 GCP 帳號後，第一件事：測金鑰限制

```bash
gcloud organizations list
```

如果有輸出，代表這個帳號掛在某個組織底下，**馬上試著建一次 service account 金鑰**，
確認會不會撞到 `iam.disableServiceAccountKeyCreation` 這條組織政策。

- 撞到、而且你們不是那個組織的管理員 → 沒辦法用 JSON key，要改走
  Workload Identity Federation，及早設定，不要等要 deploy 才發現卡住
- 沒撞到 → 照這份清單往下走，用 JSON key（比較快）

---

## 1. 啟用必要的 API

```bash
PROJECT_ID="填新的專案ID"

gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com \
  --project=$PROJECT_ID
```

- `sqladmin.googleapis.com` 只有要用 Cloud SQL 才需要，不用可以拿掉
- 要用 Firestore／Cloud Storage 的話另外加 `firestore.googleapis.com`（Storage 通常預設就開著）

---

## 2. 建 Artifact Registry repository

```bash
gcloud artifacts repositories create REPO_NAME \
  --repository-format=docker \
  --location=asia-east1 \
  --project=$PROJECT_ID
```

---

## 3. 建 service account + 掛角色

```bash
SA_NAME="hackathon-deployer"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create $SA_NAME \
  --project=$PROJECT_ID \
  --display-name="Hackathon CI/CD deployer"

for ROLE in \
  roles/artifactregistry.writer \
  roles/run.admin \
  roles/iam.serviceAccountUser \
  roles/secretmanager.secretAccessor \
  roles/cloudsql.client
do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$ROLE"
done
```

- `roles/cloudsql.client` 只有要用 Cloud SQL 才需要
- 要用 Firestore 加 `roles/datastore.user`，要用 Cloud Storage 加 `roles/storage.objectAdmin`
- 同一個 SA 身兼「CI 部署身分」與「Cloud Run 執行身分」，不要分兩個，減少一半的排查成本

```bash
gcloud iam service-accounts keys create ./sa-key.json --iam-account=$SA_EMAIL
```

金鑰內容等一下要貼進 GitHub，**貼完把本機這個檔案刪掉**。

---

## 4. 建 Secret Manager 的 secrets

```bash
# 真的 Gemini API key
echo -n "真實的_GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY \
  --data-file=- --replication-policy=automatic --project=$PROJECT_ID
```

如果要用 Cloud SQL，先建實例、拿到 instance connection name，再建這個：

```bash
echo -n '{"instance_connection_name":"PROJECT:REGION:INSTANCE","db_name":"...","db_user":"...","db_password":"..."}' | \
  gcloud secrets create CLOUD_SQL_CONFIG --data-file=- --replication-policy=automatic --project=$PROJECT_ID
```

---

## 5. GitHub repo 設定

用「Use this template」生出新 repo 後：

| 位置 | 要設什麼 |
|---|---|
| Settings → Secrets and variables → Actions → **Secrets** | `GCP_SA_KEY`（第 3 步下載的 JSON 金鑰內容） |
| Settings → Environments | 新建一個叫 `production` 的 environment（workflow 裡的 `environment: production` 對應這個） |

**這個 repo 的 `PROJECT_ID`／`SERVICE`／`REPOSITORY`／`IMAGE`／`SERVICE_ACCOUNT`／`DB_INSTANCE_CONNECTION_NAME`
是直接寫在 `.github/workflows/deploy-to-production-on-push-tag.yml` 的 `env:` 區塊裡（不是 GitHub Variables），
換帳號後要直接編輯這個檔案改成新的值，而不是去網頁設定。**

---

## 6. 驗證整條 pipeline

```bash
git tag v0.0.1-test
git push origin v0.0.1-test
```

去 repo 的 Actions 分頁看 log。跑完打：

```bash
curl https://你的CLOUD_RUN_URL/api/health
```

預期看到 `{"ok":true,"data":{"status":"ok","demo_mode":false,"db":"ok"}}`
（沒用 Cloud SQL 的話 `db` 會是 `null`，這樣也正常）。

---

## 常見卡點對照表（這次測試踩過的坑）

| 症狀 | 原因 | 解法 |
|---|---|---|
| `denied ... artifactregistry.repositories.uploadArtifacts ... or it may not exist` | `PROJECT_ID` 打錯（專案 ID 常常被 GCP 加亂數尾碼） | 用 `gcloud projects list` 確認真正的 PROJECT_ID |
| `Cloud Run Admin API has not been used ... or it is disabled` | 對應的 API 沒開 | 回第 1 步 `gcloud services enable` |
| `gcloud run deploy` 找不到 secret | Secret Manager 裡沒建那個 secret | 回第 4 步 |
| deploy 成功但 container 起來讀不到 secret | Cloud Run 的 runtime service account 跟部署用的不是同一個 | 確認 workflow 的 `--service-account` 有指到第 3 步建的 SA |
| 建 service account 金鑰時說政策擋住 | 組織政策 `iam.disableServiceAccountKeyCreation` | 回第 0 步 |