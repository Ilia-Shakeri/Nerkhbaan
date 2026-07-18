import React, { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, LifeBuoy, Loader2, MessageCircle, Plus, Send } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { toast } from 'sonner';
import { useAppContext } from '../context/AppContext';
import { api, type SupportMessage, type SupportTicket } from '../services/api';

export function SupportView() {
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<number | null>(null);
  const [messages, setMessages] = useState<SupportMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [newMessage, setNewMessage] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isNewOpen, setIsNewOpen] = useState(false);
  const [subject, setSubject] = useState('');
  const [firstMessage, setFirstMessage] = useState('');

  const t = {
    title: { fa: 'پشتیبانی', en: 'Support' },
    newTicket: { fa: 'درخواست جدید', en: 'New ticket' },
    noTickets: { fa: 'درخواستی ثبت نشده است', en: 'No support tickets' },
    select: { fa: 'یک درخواست را باز کنید', en: 'Open a ticket to see its conversation' },
    subject: { fa: 'موضوع', en: 'Subject' },
    message: { fa: 'پیام', en: 'Message' },
    create: { fa: 'ثبت درخواست', en: 'Create ticket' },
    cancel: { fa: 'انصراف', en: 'Cancel' },
    send: { fa: 'ارسال', en: 'Send' },
  };

  useEffect(() => {
    let active = true;
    api.support.listTickets()
      .then((items) => {
        if (active) setTickets(items);
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : 'Failed to load support tickets'))
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (selectedTicket === null) {
      setMessages([]);
      return;
    }
    let active = true;
    setMessagesLoading(true);
    api.support.listMessages(selectedTicket)
      .then((items) => {
        if (active) setMessages(items);
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : 'Failed to load conversation'))
      .finally(() => {
        if (active) setMessagesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedTicket]);

  const sendMessage = async () => {
    if (selectedTicket === null || !newMessage.trim()) return;
    setIsSending(true);
    try {
      const sent = await api.support.sendMessage(selectedTicket, newMessage.trim());
      setMessages((current) => [...current, sent]);
      setNewMessage('');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to send message');
    } finally {
      setIsSending(false);
    }
  };

  const createTicket = async () => {
    if (!subject.trim() || !firstMessage.trim()) return;
    setIsSending(true);
    try {
      const created = await api.support.createTicket({ subject: subject.trim(), message: firstMessage.trim() });
      setTickets((current) => [created, ...current]);
      setSelectedTicket(created.id);
      setSubject('');
      setFirstMessage('');
      setIsNewOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to create ticket');
    } finally {
      setIsSending(false);
    }
  };

  const selected = tickets.find((item) => item.id === selectedTicket);
  const panel = isDark ? 'border-white/5 bg-[#0E0E0E]/70' : 'border-black/5 bg-white/70';

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex items-center justify-between gap-4">
        <h1 className="flex items-center gap-2 text-2xl font-bold"><LifeBuoy className="text-[#D4AF37]" />{t.title[language]}</h1>
        <Button variant="primary" className="gap-2" onClick={() => setIsNewOpen(true)}><Plus size={17} />{t.newTicket[language]}</Button>
      </div>

      <div className="grid min-h-[560px] gap-4 lg:grid-cols-[320px_1fr]">
        <Card className={`overflow-hidden border ${panel}`}>
          {isLoading ? (
            <div className="flex h-full min-h-48 items-center justify-center"><Loader2 className="animate-spin text-[#D4AF37]" /></div>
          ) : tickets.length === 0 ? (
            <div className="flex h-full min-h-48 flex-col items-center justify-center gap-2 p-6 text-center text-sm text-slate-500"><MessageCircle size={30} />{t.noTickets[language]}</div>
          ) : (
            <div className="divide-y divide-black/5 dark:divide-white/5">
              {tickets.map((ticket) => (
                <button key={ticket.id} type="button" onClick={() => setSelectedTicket(ticket.id)} className={`w-full p-4 text-start transition ${selectedTicket === ticket.id ? 'bg-[#D4AF37]/15' : 'hover:bg-black/5 dark:hover:bg-white/5'}`}>
                  <div className="mb-1 flex items-center justify-between gap-2"><span className="truncate font-bold">{ticket.subject}</span><span className="shrink-0 text-[10px] uppercase text-[#D4AF37]">{ticket.status.replace(/_/g, ' ')}</span></div>
                  <div className="truncate text-xs text-slate-500">{ticket.last_message}</div>
                  <div className="mt-1 text-[10px] text-slate-400" dir="ltr">{ticket.date}</div>
                </button>
              ))}
            </div>
          )}
        </Card>

        <Card className={`flex min-h-[560px] flex-col overflow-hidden border ${panel}`}>
          {!selected ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-slate-500"><MessageCircle size={38} />{t.select[language]}</div>
          ) : (
            <>
              <div className="flex items-center gap-3 border-b border-black/5 p-4 dark:border-white/5"><button className="lg:hidden" onClick={() => setSelectedTicket(null)}>{language === 'fa' ? <ArrowRight /> : <ArrowLeft />}</button><div><div className="font-bold">{selected.subject}</div><div className="text-xs text-[#D4AF37]">{selected.status.replace(/_/g, ' ')}</div></div></div>
              <div className="flex-1 space-y-3 overflow-y-auto p-4">
                {messagesLoading ? <div className="flex h-full items-center justify-center"><Loader2 className="animate-spin text-[#D4AF37]" /></div> : messages.map((message) => (
                  <div key={message.id} className={`flex ${message.from_user === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[78%] rounded-2xl px-4 py-3 text-sm ${message.from_user === 'user' ? 'bg-[#D4AF37] text-black' : isDark ? 'bg-white/5 text-white' : 'bg-black/5 text-[#3B2E13]'}`}>
                      <div className="whitespace-pre-wrap break-words">{message.content}</div><div className="mt-1 text-[9px] opacity-60" dir="ltr">{new Date(message.timestamp).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex gap-2 border-t border-black/5 p-4 dark:border-white/5"><Input value={newMessage} onChange={(event) => setNewMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendMessage(); } }} placeholder={t.message[language]} /><Button variant="primary" size="icon" disabled={isSending || !newMessage.trim()} onClick={() => void sendMessage()}>{isSending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}</Button></div>
            </>
          )}
        </Card>
      </div>

      <Modal isOpen={isNewOpen} onClose={() => setIsNewOpen(false)} title={t.newTicket[language]}>
        <div className="space-y-4"><label className="block space-y-2 text-sm font-medium"><span>{t.subject[language]}</span><Input value={subject} onChange={(event) => setSubject(event.target.value)} /></label><label className="block space-y-2 text-sm font-medium"><span>{t.message[language]}</span><textarea value={firstMessage} onChange={(event) => setFirstMessage(event.target.value)} rows={6} className="w-full resize-none rounded-xl border bg-transparent p-3 outline-none focus:ring-2 focus:ring-[#D4AF37]/40 dark:border-white/10" /></label><div className="flex gap-3"><Button variant="primary" className="flex-1" disabled={isSending || !subject.trim() || !firstMessage.trim()} onClick={() => void createTicket()}>{isSending ? <Loader2 size={16} className="animate-spin" /> : t.create[language]}</Button><Button variant="ghost" className="flex-1" onClick={() => setIsNewOpen(false)}>{t.cancel[language]}</Button></div></div>
      </Modal>
    </div>
  );
}
