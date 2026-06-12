"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "@/lib/types";
import { LogoMark } from "./Logo";
import { Sources } from "./Sources";
import { ThinkingStatus } from "./ThinkingStatus";

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-brand-700 to-brand-900 px-4 py-3 text-[15px] whitespace-pre-wrap text-white shadow-md shadow-brand-900/10">
          {message.content}
        </div>
      </div>
    );
  }

  const streaming = !message.done;
  const nFuentes = message.fuentes.length;

  return (
    <div className="flex gap-3">
      <LogoMark className="mt-0.5 h-9 w-9 shrink-0 drop-shadow-sm" />
      <div className="min-w-0 flex-1">
        {/* Resumen de la búsqueda: visible apenas termina la recuperación,
            antes de que empiece a llegar la respuesta, y queda fijo. */}
        {nFuentes > 0 && (
          <div className="fade-up mb-2 inline-flex items-center gap-1.5 rounded-full border border-accent-500/30 bg-amber-50/70 px-3 py-1 text-xs font-medium text-brand-800">
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5 text-accent-600">
              <path
                fillRule="evenodd"
                d="M2 4.75A2.75 2.75 0 0 1 4.75 2h10.5A2.75 2.75 0 0 1 18 4.75v10.5A2.75 2.75 0 0 1 15.25 18H4.75A2.75 2.75 0 0 1 2 15.25V4.75Zm3 .75a.75.75 0 0 1 .75-.75h8.5a.75.75 0 0 1 0 1.5h-8.5A.75.75 0 0 1 5 5.5Zm0 3a.75.75 0 0 1 .75-.75h8.5a.75.75 0 0 1 0 1.5h-8.5A.75.75 0 0 1 5 8.5Zm0 3a.75.75 0 0 1 .75-.75h5.5a.75.75 0 0 1 0 1.5h-5.5a.75.75 0 0 1-.75-.75Z"
                clipRule="evenodd"
              />
            </svg>
            {nFuentes} artículo{nFuentes === 1 ? "" : "s"} recuperado{nFuentes === 1 ? "" : "s"}
            {message.segundos !== undefined && (
              <span className="text-slate-400">· {message.segundos}s</span>
            )}
          </div>
        )}

        {streaming && message.content === "" && <ThinkingStatus fases={message.fases} />}

        {message.content && (
          <div className="fade-up prose prose-slate prose-sm max-w-none rounded-2xl rounded-tl-md border border-slate-200/80 bg-white px-5 py-4 shadow-sm shadow-slate-200/60 prose-headings:font-serif prose-headings:text-brand-900 prose-p:leading-relaxed prose-strong:text-brand-900 prose-a:text-brand-600">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            {streaming && (
              <span className="ml-0.5 inline-block h-4 w-2 animate-pulse rounded-sm bg-accent-500 align-text-bottom" />
            )}
            {message.done && <Sources fuentes={message.fuentes} />}
          </div>
        )}

        {message.error && (
          <div className="mt-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {message.error}
          </div>
        )}
      </div>
    </div>
  );
}
