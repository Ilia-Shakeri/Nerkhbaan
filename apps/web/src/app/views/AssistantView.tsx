import React, { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { Bot, Check, Loader2, MessageSquarePlus, Pencil, Send, Trash2, X } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { useAppContext } from '../context/AppContext';
import { api, type ChatMessage, type ChatSessionSummary } from '../services/api';
import { toast } from 'sonner';

export function AssistantView() {
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';
  const shouldReduceMotion = useReducedMotion();

  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameDraft, setRenameDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  const t = {
    title: { fa: 'دستیار هوشمند', en: 'Smart Assistant' },
    newChat: { fa: 'گفتگوی جدید', en: 'New chat' },
    placeholder: { fa: 'سوال خود را بنویسید...', en: 'Type your question...' },
    empty: {
      fa: 'درباره بازار طلا، ارز و رمزارز بپرسید',
      en: 'Ask about gold, currency and crypto markets'
    },
    noSessions: { fa: 'گفتگویی ثبت نشده', en: 'No saved chats' },
    sendFail: { fa: 'پاسخ در دسترس نیست', en: 'Reply is unavailable' },
    saved: { fa: 'ذخیره شد', en: 'Saved' },
    deleted: { fa: 'حذف شد', en: 'Deleted' },
    ttl: { fa: 'تاریخچه پس از یک ماه حذف می‌شود', en: 'History is deleted after one month' },
    rename: { fa: 'تغییر نام گفتگو', en: 'Rename chat' },
    cancelRename: { fa: 'لغو تغییر نام', en: 'Cancel rename' },
    delete: { fa: 'حذف گفتگو', en: 'Delete chat' },
    deleteConfirm: { fa: 'این گفتگو حذف شود؟', en: 'Delete this chat?' },
    send: { fa: 'ارسال پیام', en: 'Send message' },
  };

  const refreshSessions = async () => {
    const data = await api.insights.listSessions();
    setSessions(data);
    return data;
  };

  useEffect(() => {
    refreshSessions()
      .then((data) => {
        if (data[0]) setActiveSessionId(data[0].id);
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : t.sendFail[language]))
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      return;
    }
    api.insights
      .getSession(activeSessionId)
      .then((session) => setMessages(session.messages))
      .catch((error) => toast.error(error instanceof Error ? error.message : t.sendFail[language]));
  }, [activeSessionId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: shouldReduceMotion ? 'auto' : 'smooth',
    });
  }, [messages, isSending, shouldReduceMotion]);

  const startNewChat = () => {
    setActiveSessionId(null);
    setMessages([]);
    setDraft('');
  };

  const handleSend = async () => {
    const text = draft.trim();
    if (!text || isSending) return;

    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content: text }];
    setMessages(nextMessages);
    setDraft('');
    setIsSending(true);
    try {
      const result = await api.insights.chat(nextMessages, language, activeSessionId);
      setActiveSessionId(result.session_id);
      setMessages((prev) => [...prev, { role: 'assistant', content: result.reply }]);
      await refreshSessions();
    } catch (error) {
      setMessages(messages);
      toast.error(error instanceof Error ? error.message : t.sendFail[language]);
    } finally {
      setIsSending(false);
    }
  };

  const renameSession = async (sessionId: number) => {
    const title = renameDraft.trim();
    if (!title) return;
    try {
      await api.insights.renameSession(sessionId, title);
      setRenamingId(null);
      setRenameDraft('');
      await refreshSessions();
      toast.success(t.saved[language]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.sendFail[language]);
    }
  };

  const deleteSession = async (sessionId: number) => {
    if (!window.confirm(t.deleteConfirm[language])) return;
    try {
      await api.insights.deleteSession(sessionId);
      const next = sessions.filter((session) => session.id !== sessionId);
      setSessions(next);
      if (activeSessionId === sessionId) {
        setActiveSessionId(next[0]?.id ?? null);
        if (!next[0]) setMessages([]);
      }
      toast.success(t.deleted[language]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.sendFail[language]);
    }
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className={`text-3xl font-bold ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>{t.title[language]}</h1>
          <p className={`mt-1 text-xs ${isDark ? 'text-[#8C7A52]' : 'text-[#8A6A25]'}`}>{t.ttl[language]}</p>
        </div>
        <Button onClick={startNewChat} className="gap-2 rounded-xl bg-[#D4AF37] text-black hover:bg-[#E8C45A]">
          <MessageSquarePlus size={18} />
          {t.newChat[language]}
        </Button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        <Card className={`min-h-[180px] overflow-hidden rounded-2xl ${isDark ? 'border-white/5 bg-[#0E0E0E]/60' : 'border-black/5 bg-white/70'}`}>
          <div className="h-full overflow-y-auto p-3">
            {isLoading ? (
              <div className="flex h-full items-center justify-center">
                <Loader2 className="animate-spin text-[#D4AF37]" size={22} />
              </div>
            ) : sessions.length === 0 ? (
              <div className={`p-4 text-center text-sm ${isDark ? 'text-[#8C7A52]' : 'text-[#8A6A25]'}`}>{t.noSessions[language]}</div>
            ) : (
              <div className="space-y-2">
                {sessions.map((session) => (
                  <div
                    key={session.id}
                    className={`flex min-h-12 items-center gap-1 rounded-xl border p-1.5 transition-[background-color,border-color] ${
                      activeSessionId === session.id
                        ? 'border-[#D4AF37]/60 bg-[#D4AF37]/10'
                        : isDark ? 'border-white/5 hover:bg-white/5' : 'border-black/5 hover:bg-[#D4AF37]/5'
                    }`}
                  >
                    {renamingId === session.id ? (
                      <form className="flex min-w-0 flex-1 gap-1" onSubmit={(event) => { event.preventDefault(); void renameSession(session.id); }}>
                        <Input value={renameDraft} onChange={(event: React.ChangeEvent<HTMLInputElement>) => setRenameDraft(event.target.value)} className="h-11 min-w-0 text-xs" aria-label={t.rename[language]} autoFocus />
                        <Button type="submit" size="icon" className="h-11 w-11 bg-[#D4AF37] text-black" aria-label={t.rename[language]}><Check size={16} /></Button>
                        <Button type="button" size="icon" variant="ghost" className="h-11 w-11" onClick={() => setRenamingId(null)} aria-label={t.cancelRename[language]}><X size={16} /></Button>
                      </form>
                    ) : (
                      <>
                        <button type="button" onClick={() => setActiveSessionId(session.id)} aria-current={activeSessionId === session.id ? 'true' : undefined} className="min-h-11 min-w-0 flex-1 rounded-lg px-2 text-start">
                          <span className={`block truncate text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{session.title}</span>
                        </button>
                        <button type="button" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[#D4AF37] transition-colors hover:bg-[#D4AF37]/10 active:scale-95" onClick={() => { setRenamingId(session.id); setRenameDraft(session.title); }} aria-label={`${t.rename[language]}: ${session.title}`}><Pencil size={16} /></button>
                        <button type="button" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-red-400 transition-colors hover:bg-red-500/10 active:scale-95" onClick={() => void deleteSession(session.id)} aria-label={`${t.delete[language]}: ${session.title}`}><Trash2 size={16} /></button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>

        <Card className={`flex min-h-0 flex-col rounded-2xl ${isDark ? 'border-white/5 bg-[#0E0E0E]/60' : 'border-black/5 bg-white/70'}`}>
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4" role="log" aria-live="polite" aria-relevant="additions">
            {messages.length === 0 ? (
              <div className="flex h-full items-center justify-center">
                <div className="text-center">
                  <Bot size={48} className={`mx-auto mb-4 ${isDark ? 'text-gray-600' : 'text-gray-400'}`} />
                  <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>{t.empty[language]}</p>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {messages.map((msg, index) => (
                  <motion.div key={`${msg.role}-${index}`} initial={{ opacity: 0, y: shouldReduceMotion ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', bounce: 0, duration: 0.28 }} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[78%] rounded-2xl px-4 py-3 text-sm leading-7 whitespace-pre-wrap ${msg.role === 'user' ? 'bg-[#D4AF37] text-black' : isDark ? 'bg-[#1A1A1A] text-white' : 'bg-gray-100 text-[#3B2E13]'}`}>
                      {msg.content}
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
            {isSending && (
              <div className="mt-4 flex justify-start">
                <div className={`rounded-2xl px-4 py-3 ${isDark ? 'bg-[#1A1A1A]' : 'bg-gray-100'}`}>
                  <Loader2 size={18} className="animate-spin text-[#D4AF37]" />
                </div>
              </div>
            )}
          </div>

          <div className={`border-t p-4 ${isDark ? 'border-white/10' : 'border-black/10'}`}>
            <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void handleSend(); }}>
              <Input
                value={draft}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
                onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    handleSend();
                  }
                }}
                placeholder={t.placeholder[language]}
                className={`flex-1 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414]' : 'border-[#D4AF37]/30 bg-white'}`}
              />
              <Button type="submit" disabled={isSending || !draft.trim()} className="h-11 w-11 bg-[#D4AF37] text-black disabled:opacity-50" aria-label={t.send[language]}>
                {isSending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              </Button>
            </form>
          </div>
        </Card>
      </div>
    </div>
  );
}
