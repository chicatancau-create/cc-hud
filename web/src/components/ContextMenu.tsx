import { useEffect, useMemo, useRef, useState } from "react";
import type { MenuModel, MenuNode } from "../types";

interface Props {
  model: MenuModel;
  x: number;
  y: number;
  onPick: (id: string) => void;
  onClose: () => void;
}

function nodeKey(node: MenuNode, i: number) {
  return `${node.id}:${i}`;
}

/** 主面板右键菜单：只渲染 Python 下发的同一份命令树，不在前端复制业务。 */
export function ContextMenu({ model, x, y, onPick, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();      // 不要触发 App 里「Esc 收起小卡」的旧快捷键
        onClose();
      }
    };
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("mousedown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("mousedown", onDown, true);
    };
  }, [onClose]);

  const style = useMemo(() => ({
    left: Math.min(x, Math.max(0, window.innerWidth - 260)),
    top: Math.min(y, Math.max(0, window.innerHeight - 320))
  }), [x, y]);

  const renderNodes = (nodes: MenuNode[]) => nodes.map((node, i) => {
    if (node.kind === "separator") return <div key={nodeKey(node, i)} className="menu-sep" role="separator" />;
    if (node.kind === "submenu") {
      const key = nodeKey(node, i);
      const isOpen = open === key;
      return (
        <div key={key} className="menu-sub" onMouseEnter={() => setOpen(key)}>
          <button type="button" className="menu-item sub" aria-haspopup="menu" aria-expanded={isOpen}
            data-testid={`menu-${node.id}`}
            onClick={() => setOpen(key)}>
            <span className="menu-check">{node.danger ? "⚠" : ""}</span>
            <span className="menu-title">{node.title}</span>
            <span className="menu-arrow">›</span>
          </button>
          {isOpen ? <div className="menu-sub-list" role="menu">{renderNodes(node.children)}</div> : null}
        </div>
      );
    }
    const checked = node.kind === "radio" || node.kind === "check";
    return (
      <button key={nodeKey(node, i)} type="button"
        className={`menu-item${node.danger ? " danger" : ""}${checked && node.checked ? " on" : ""}`}
        role={node.kind === "radio" ? "menuitemradio" : node.kind === "check" ? "menuitemcheckbox" : "menuitem"}
        aria-checked={checked ? Boolean(node.checked) : undefined}
        disabled={!node.enabled}
        data-testid={`menu-${node.id}`}
        onClick={() => { onClose(); onPick(node.id); }}>
        <span className="menu-check">{checked ? (node.checked ? "✓" : "") : ""}</span>
        <span className="menu-title">{node.title}</span>
      </button>
    );
  });

  return (
    <div ref={ref} className="context-menu" style={style} role="menu" data-testid="context-menu">
      {renderNodes(model.items)}
    </div>
  );
}
