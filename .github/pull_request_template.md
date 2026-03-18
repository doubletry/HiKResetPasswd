# PR 检查清单 / PR Checklist

在提交 Review 之前，请确认以下所有条目均已通过。
Before requesting a review, please confirm **all** items below are checked.

---

## 🔧 自动检查 (Automated Checks — must all pass in CI)

The **Checks** workflow must be green before review is requested:

- [ ] `ruff check` — Python 代码风格 / Python code style
- [ ] `vue-tsc --build` — TypeScript 类型检查 / TypeScript type check
- [ ] `npm run lint` — Frontend ESLint + Oxlint

The **Tests** workflow must be green before review is requested:

- [ ] `pytest` — 所有后端单元测试通过 / All backend unit tests pass
- [ ] `vite build` — 前端无编译错误 / Frontend builds without errors

---

## ✅ 功能性检查 / Functional Checklist

- [ ] 变更描述清晰，说明了修改了什么以及为什么 / Changes are clearly described (what and why)
- [ ] 新功能/修复已手动验证 / New feature or fix has been manually verified
- [ ] 已为新功能或 bug 修复添加或更新了测试 / Tests added or updated for the change
- [ ] 没有引入新的安全漏洞（敏感数据处理、SSRF 防护等）/ No new security vulnerabilities introduced
- [ ] 没有提交 `.env` 或包含密钥的文件 / No `.env` or secret-containing files committed

---

## 📝 变更说明 / Description of Changes

> 请在此简要描述本次 PR 的主要改动。
> Briefly describe the main changes in this PR.

(placeholder — replace with your description)
