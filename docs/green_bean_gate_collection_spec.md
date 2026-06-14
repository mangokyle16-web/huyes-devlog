# Green Bean Gate — 瑕疵偵測採集 + 實施 Spec

> 2026-06-14 定案。第一重點功能:**烘焙前生豆風險閘門(pre-roast green-bean risk gate)**,客群=自家烘豆玩家 / prosumer 微烘焙者。同一套設備以「綠豆→烘焙」配對提供 quaker 驗證、新鮮度、Agtron 作為烘後答案。
> 含 Codex(consult session 019ec6c8)壓力測試後的具體實施計畫。

---

## 1. 產品定位(硬需求)

**問題:** 自家烘豆玩家買了一批生豆,正要花時間烘,卻無法在烘壞或喝到問題前,可靠得知裡面有沒有發霉/過發酵/黑豆/會變 quaker 的豆。

**產品:** Green Bean Gate —— 烘焙前對一批生豆做 **接受 / 剔除 / 退貨** 判定。

**不是:** 消費者挑烘焙豆(烘豆廠上游已 QC,市場弱)。

**食安界線:** 只做「發霉/發酵風險篩查」,**不宣稱毒素認證**。VNIR 350–950nm 缺 1450/1940nm 水吸收帶,無法做 OTA 認證(EU 烘焙咖啡 OTA-A 上限 3.0 µg/kg);要食安說法須對子集送實驗室。

---

## 2. 模型優先序

1. **A — Siamese 光譜分類器(主):** VNIR 價值所在 —— 發霉、過發酵、黑、褪色老化、未熟/quaker 前兆。few-shot(Hu et al. 2025 LWT 235,118631)。
2. **B — YOLO 視覺(次):** 僅作裁切/分割、粗損傷、石頭異物、嚴重蟲孔。**v1 不做完整烘焙豆多分類。**

**模型不靠單一訊號**(太脆),用堆疊:
```
10-band 校正光譜 + band ratios/正規化反射
+ 每批 robust 正規化
+ 全域正常原型 + 瑕疵原型
+ Siamese 距離分數
+ 簡單異常基線(sanity check)
```

**輸出標籤(二元 + 原因桶,非 SCA 分類博物館):**
`accept` / `reject:mold-risk` / `reject:ferment-risk` / `reject:black` / `reject:unknown-anomaly` / `abstain:calibration-or-lot-out-of-domain`
> `unknown-anomaly` 與 `abstain` 必備——否則模型會「說謊」(硬湊一個類)。

---

## 3. 核心採集協定:Scored Micro-lot Pairing

**不做 per-bean 跨烘焙身分追蹤(脆弱、昂貴、v1 不需要)。不做單豆烘焙(熱質量/氣流/失水/焦化全不對,毀掉標籤效度)。不做純 lot-level(干擾太多)。**

改用**分數分層微批配對**:
```
逐顆掃描生豆 → 每顆評分 clean / borderline / reject-like
→ 依分層裝入貼標網袋膠囊(15–30 顆/膠囊)
   capsule A1–A3: model-clean
   capsule B1–B3: borderline
   capsule C1–C3: high-risk
   + 同批散裝填充豆(湊正常烘焙質量)
→ 全部放進「同一個正常烘焙批」一起烘(輪換膠囊位置、做複製樣本)
→ 烘後逐膠囊倒出掃描:數 quaker、Agtron、視覺瑕疵、新鮮度
→ 驗證:生豆風險分數是否讓「壞的烘後結果」集中於 C 膠囊
```
- 膠囊建議:不鏽鋼細網茶球 / 小烘焙膠囊 / 自製網袋,實體 + 軟體雙標。
- 關鍵不是「這顆生豆變成那顆 quaker」,而是「**風險分數有沒有富集壞結果**」。

---

## 4. 採集對象與數量(MVP)

### Phase 2 先收:正常生豆參考庫(最重要,先於瑕疵)
> 沒有正常多樣性,瑕疵資料就沒用 —— 模型會把每顆日曬豆判成瑕疵。

| 維度 | 目標 |
|---|---|
| 生豆批數 | 8–12 批 |
| 處理法 | ≥3 種(水洗 / 日曬 / 蜜處理) |
| 產地 | 3–4 個 |
| 每批顆數 | 100–150 顆 |
| 合計 | **約 1,000–1,800 顆正常豆** |
| 記錄 | 含水量 / 存放天數(若可) |

**v1 砍掉:** 低咖啡因、怪異厭氧/實驗性批(會炸 false positive),baseline 穩前不收。

### Phase 3 瑕疵 bootstrap(few-shot,少量)
| 類別 | 目標數量 | 標籤驗證 |
|---|---|---|
| 發霉 / 真菌 / 受潮 | 40–60 顆 | 來源確認;食安宣稱才送實驗室 OTA |
| 過發酵 / 酸 | 40–60 顆 | **杯測或供應商確認**,不可目視猜 |
| 全 / 部分黑 | 40–60 顆 | 視覺明確 |
| 未熟 / quaker 前兆 | 100–200 顆 | **僅透過微批烘焙驗證**,不可肉眼標生豆 quaker |
| unknown 光譜異常 | — | 拿不到真陽性就對正常豆跑異常偵測,叫「風險篩查」 |

---

## 5. 資料 Ledger(先 boring CSV/SQLite,UI later)

每筆掃描記錄:
```
lot_id, session_id, bean_id, timestamp,
calib_state(white/dark), camera_settings,
band_mean[10], band_std[10], rgb_crop_path,
density/weight_estimate(若有),
process, origin, moisture, storage_age,
capsule_id(微批), risk_score, label
```
- 加 **白/暗校正**;校正漂移過大 → 拒收該掃描(進 `abstain`)。

### 推理時參考集設計
- **全域正常庫**:依 處理/產地/含水量/存放 分層。
- **當批參考**:隨機 50–100 顆,剔除離群後取 robust centroid。
- **瑕疵原型**:每個 reject 原因少量 few-shot 範例。

### v1 判定流程
```
掃 300–500 顆生豆
→ 由最低風險多數建「該批正常 centroid」
→ 每顆對 全域正常 / 同批正常 / 瑕疵原型 評分
→ 回傳: %接受, %剔除, 原因桶, 信心, 建議動作(clean / sort / return lot)
```

---

## 6. v1 成功指標(唯一)

```
Reject Enrichment Lift @ Clean-Lot Waste Rate
= (被剔除生豆微批的 烘後 缺陷/quaker/杯測失敗率)
  ÷ (被接受微批的 同率)
```
**通過條件:≥ 5× 富集,且在已知乾淨批上誤剔 ≤ 3%。**
> SCA 多分類的 accuracy/F1 是噪音。優化「信任」不是「分類器優雅度」:剔除的豆看起來確實可疑、剔除微批烘/喝起來確實更差、乾淨批不被冤枉。

---

## 7. 綠→烘配對的角色(v1 範圍)

per-bean 配對 **v1 不需要**。配對只用於:
1. **驗證風險富集**(高風險 C 膠囊應產生更多 quaker/瑕疵/壞杯)。
2. **之後**訓練 quaker 前兆模型(先統計、非 per-bean)。
3. 把 **Agtron / 新鮮度**(批/微批屬性)掛回同批 —— 掃烘後膠囊時順帶採到。
> 新鮮度時鐘 = 順風車資料,**不列入 v1 驗證指標**(v1 用 Reject Enrichment Lift 證明)。

---

## 8. Top 3 失敗模式(設計時防範)

1. **正常變異造成 false-positive 崩潰** — 日曬/蜜/老化/高含水/怪產地豆光譜可能像瑕疵。→ 多正常批 + 每批正規化 + abstain。
2. **垃圾標籤** — 視覺「霉」≠OTA、「酸」常是猜、quaker 要烘後才知。→ 杯測 + 供應商確認 + 微批烘焙驗證 + 毒素宣稱才送實驗室。
3. **烘焙驗證假象** — 膠囊烘法不同。→ 同批一起烘、輪換位置、複製樣本、同批內比較分層。

---

## 9. 現在砍掉(v1 不做)

- 跨滾筒烘焙的 per-bean 身分系統、單豆烘焙。
- 完整烘焙豆 YOLO 多分類(black/broken/defect/unripe)。
- 破裂/缺損/貝殼當優先類(視覺、低痛點、易手挑、VNIR 價值弱)。
- 乾果莢/漂浮豆/補齊稀有 SCA 分類(分類學表演)。
- OTA 安全宣稱。
- 把新鮮度時鐘當 v1 驗證。
- 低咖啡因/怪批(直到 baseline 穩)。

---

## 10. 與既有採集排程整合

- **提案15 好豆批次(密度→重量)**:批次級 conveyor 採集,與本案的「正常生豆庫」可共用採集場次(同一批掃描順帶記 10-band + 密度進 ledger)。
- **Agtron / 新鮮度**:在掃描烘後微批時順帶採集。
- 相關文件:`docs/proposals/08_瑕疵豆多分類升級.md`、`docs/superpowers/plans/2026-06-01-siamese-bean-defect.md`、`docs/proposals/15_VNIR密度修正分段計劃.md`。

---

*實施計畫經 Codex(consult)壓力測試;核心貢獻:micro-lot 膠囊配對協定、正常庫優先、Reject Enrichment Lift 指標、abstain/unknown-anomaly 桶。*
