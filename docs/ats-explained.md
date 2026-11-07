# 关于「ATS 分数」/ About "ATS scores"

## 中文

「ATS 分数」没有统一标准。真正的招聘系统（如 Workday、Greenhouse）不会给你的履历打一个通用分数，市面上各种分数都是各家自定的规则。这里的分数是我们的规则：检查履历能不能被系统正确读取、内容写得好不好、关键词是否覆盖目标职位。每一项都列出扣分原因，请把它当成检查清单，而不是录取概率。

### 三个部分怎么算

| 部分 | 怎么算 | 检查项目 |
|---|---|---|
| 可解析度 | 程序规则，不用 LLM；100 分减去各项扣分 | 能否抽出文字（扫描图档会失败）、表格、双栏、文字方块、标准标题（Experience / Education / Skills）、联系方式、日期格式一致、档案格式、页数（只提示） |
| 内容品质 | LLM 按固定 rubric 评，四项各 25 分 | 量化成果、行动动词开头、具体不重复、篇幅；程序先算好统计（有数字的 bullet 数、弱开头、重复）交给模型参考 |
| 关键词覆盖 | LLM 列出目标职位常见技能，程序比对履历文字 | 核心技能权重 ×2；只有在你确实具备时才加进履历 |

## English

There is no universal "ATS score". Real applicant tracking systems (such as Workday or Greenhouse) do not give your resume a single standard score; every score you see online follows that vendor's own rules. This score follows ours: whether systems can read your resume correctly, how well the content is written, and whether keywords cover your target role. Every deduction is explained. Treat it as a checklist, not as your chance of getting hired.
