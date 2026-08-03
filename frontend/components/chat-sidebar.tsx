"use client";

import {
  LogOut,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  ShoppingBag,
  Trash2,
} from "lucide-react";

import type { ChatSession } from "@/lib/types";

type ChatSidebarProps = {
  sessions: ChatSession[];
  activeId: string | null;
  collapsed: boolean;
  userEmail: string | null;
  onToggle: () => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onSignOut: () => void;
};

export function ChatSidebar({
  sessions,
  activeId,
  collapsed,
  userEmail,
  onToggle,
  onNewChat,
  onSelect,
  onDelete,
  onSignOut,
}: ChatSidebarProps) {
  return (
    <aside
      className={`flex h-full shrink-0 flex-col border-r border-[#d3e0eb] bg-[#ecf2f8] transition-all duration-200 ${
        collapsed ? "w-[56px]" : "w-72"
      }`}
    >
      <div className="flex items-center gap-2 border-b border-[#dde7f0] p-3">
        <button
          type="button"
          onClick={onToggle}
          className="rounded-lg p-2 text-slate-400 transition hover:bg-[#dfe9f1] hover:text-slate-700"
          aria-label="Toggle sidebar"
        >
          {collapsed ? (
            <PanelLeftOpen className="h-5 w-5" />
          ) : (
            <PanelLeftClose className="h-5 w-5" />
          )}
        </button>
        {!collapsed && (
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-sky-400 to-blue-500 text-white shadow-sm">
              <ShoppingBag className="h-4 w-4" />
            </div>
            <span className="truncate text-sm font-bold text-slate-800">
              ShopMate AI
            </span>
          </div>
        )}
      </div>

      <div className="p-3">
        <button
          type="button"
          onClick={onNewChat}
          className={`flex w-full items-center gap-2 rounded-xl bg-gradient-to-r from-sky-400 to-blue-500 px-3 py-2.5 text-sm font-medium text-white shadow-md shadow-sky-200/70 transition hover:from-sky-300 hover:to-blue-400 ${
            collapsed ? "justify-center px-2" : ""
          }`}
        >
          <MessageSquarePlus className="h-4 w-4 shrink-0" />
          {!collapsed && <span>เริ่มแชทใหม่</span>}
        </button>
      </div>

      {!collapsed && (
        <div className="flex-1 overflow-y-auto px-3 pb-2">
          <p className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            ประวัติแชท
          </p>
          {sessions.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-slate-400">
              ยังไม่มีประวัติแชท
            </p>
          ) : (
            <ul className="space-y-1">
              {sessions.map((session) => (
                <li key={session.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(session.id)}
                    className={`w-full rounded-xl px-3 py-2.5 pr-9 text-left text-sm transition ${
                      activeId === session.id
                        ? "bg-sky-100 font-medium text-sky-900 ring-1 ring-sky-200/70"
                        : "text-slate-600 hover:bg-[#e2ebf3]"
                    }`}
                  >
                    <span className="line-clamp-2">{session.title}</span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(session.id);
                    }}
                    className="absolute right-1.5 top-1/2 hidden -translate-y-1/2 rounded-lg p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-500 group-hover:block"
                    aria-label="Delete chat"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-auto border-t border-[#dde7f0] p-3">
        {!collapsed && userEmail && (
          <p className="truncate px-2 pb-1.5 text-xs text-slate-400">{userEmail}</p>
        )}
        <button
          type="button"
          onClick={onSignOut}
          className={`flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-sm text-slate-500 transition hover:bg-[#e2ebf3] hover:text-slate-800 ${
            collapsed ? "justify-center px-2" : ""
          }`}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span>ออกจากระบบ</span>}
        </button>
      </div>
    </aside>
  );
}
