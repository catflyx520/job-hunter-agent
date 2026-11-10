import { useState } from "react";

/** 目标职位 tag：点 tag 本身切换启用 / 停用，× 删除，旁边输入框加新的（「A, B」会拆成两个）。
 * 停用的职位留在清单里，但搜索、评分、关键词检查都不用。 */
export default function RoleTags({
  roles,
  paused,
  onChange,
  disabled,
}: {
  roles: string[];
  paused: string[];
  onChange: (roles: string[], paused: string[]) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const off = new Set(paused);

  const add = () => {
    const extra = [...new Set(draft.split(/[,，]/).map((x) => x.trim()))].filter((x) => x && !roles.includes(x));
    if (extra.length) onChange([...roles, ...extra], paused);
    setDraft("");
  };

  return (
    <div className="chips">
      {roles.map((r) => {
        const on = !off.has(r);
        return (
          <span className={`chip role-chip${on ? "" : " off"}`} key={r}>
            <button
              type="button"
              className="chip-toggle"
              aria-pressed={on}
              title={on ? "启用中，点一下停用" : "已停用，点一下启用"}
              disabled={disabled}
              onClick={() => onChange(roles, on ? [...paused, r] : paused.filter((x) => x !== r))}
            >
              <span aria-hidden="true">{on ? "✓" : "○"}</span> {r}
            </button>
            <button
              type="button"
              aria-label={`删除 ${r}`}
              disabled={disabled}
              onClick={() => onChange(roles.filter((x) => x !== r), paused.filter((x) => x !== r))}
            >
              ×
            </button>
          </span>
        );
      })}
      <input
        aria-label="新增目标职位"
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        placeholder="例如 AI Engineer，按 Enter 添加"
        style={{ flex: "1 1 180px", minWidth: 0 }}
      />
      <button type="button" onClick={add} disabled={disabled || !draft.trim()}>
        添加
      </button>
    </div>
  );
}
