import React, { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
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
    ttl: { fa: 'تاریخچه پس از یک ماه حذف می‌شود', en: 'History is deleted after one month' }
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
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, isSending]);

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
                  <button
                    key={session.id}
                    type="button"
                    onClick={() => setActiveSessionId(session.id)}
                    className={`w-full rounded-xl border p-3 text-start transition ${
                      activeSessionId === session.id
                        ? 'border-[#D4AF37]/60 bg-[#D4AF37]/10'
                        : isDark ? 'border-white/5 hover:bg-white/5' : 'border-black/5 hover:bg-[#D4AF37]/5'
                    }`}
                  >
                    {renamingId === session.id ? (
                      <div className="flex gap-1">
                        <Input value={renameDraft} onChange={(event: React.ChangeEvent<HTMLInputElement>) => setRenameDraft(event.target.value)} className="h-8 text-xs" autoFocus />
                        <Button size="icon" className="h-8 w-8 bg-[#D4AF37] text-black" onClick={() => renameSession(session.id)}><Check size={14} /></Button>
                        <Button size="icon" variant="ghost" className="h-8 w-8" onClick={() => setRenamingId(null)}><X size={14} /></Button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className={`flex-1 truncate text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{session.title}</span>
                        <Pencil size={14} className="text-[#D4AF37]" onClick={(event) => { event.stopPropagation(); setRenamingId(session.id); setRenameDraft(session.title); }} />
                        <Trash2 size={14} className="text-red-400" onClick={(event) => { event.stopPropagation(); deleteSession(session.id); }} />
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </Card>

        <Card className={`flex min-h-0 flex-col rounded-2xl ${isDark ? 'border-white/5 bg-[#0E0E0E]/60' : 'border-black/5 bg-white/70'}`}>
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4">
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
                  <motion.div key={`${msg.role}-${index}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
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
            <div className="flex gap-2">
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
              <Button onClick={handleSend} disabled={isSending || !draft.trim()} className="bg-[#D4AF37] text-black disabled:opacity-50">
                {isSending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
