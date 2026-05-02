# SmartEvac Infra — DynamoDB + Dijkstra

**負責人**：lxh

整合說明、步驟、AWS 資源清單請見 `hackerson/INTEGRATION.md`。

---

## 文件索引

| 文件 | 說明 |
|---|---|
| `DESIGN.md` | DynamoDB schema 與 Dijkstra 演算法技術設計 |
| `TEST_RESULTS.md` | 離線測試 + DynamoDB 整合測試 + AWS 端到端驗證記錄 |
| `hackerson/INTEGRATION.md` | 整合步驟、函式對照、環境變數（主文件） |

---

## 快速執行

```powershell
# 使用 smartevac-cloud 的 venv（Windows）
..\smartevac-cloud\.venv\Scripts\python test_routing.py      # 離線 Dijkstra 測試
..\smartevac-cloud\.venv\Scripts\python test_integration.py  # DynamoDB 整合測試
..\smartevac-cloud\.venv\Scripts\python seed_topology.py     # 重新 seed 拓撲
```

---

## 拓撲（5 節點）

```
N1 (North Exit) ──8m── N2 (NW Corridor) ──12m── N3 (Central Hall)
                                                       │
                                                      10m
                                                       │
                          N5 (South Exit) ──9m──  N4 (SE Corridor)
```

出口：N1（北側）、N5（南側）
