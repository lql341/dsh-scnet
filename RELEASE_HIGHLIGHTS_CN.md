- README 的版本亮点改为由 canonical 单一来源生成；每次发布替换当前版本区块，不再逐版
  堆叠成流水账。
- canonical Skill 和 Codex Plugin 在校验通过后自动创建 Git tag 与 GitHub Release。
- DSH 分发仓库在同步版本进入 `main` 后，自动完成 npm 发布、Git tag 和 GitHub Release。
