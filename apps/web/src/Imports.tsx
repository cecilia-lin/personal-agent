import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Check, FileText, Upload, X } from 'lucide-react';
import { api, money, parseMoney, type BillDraft, type Dashboard } from './api';

export function SourceDialog({ source, close }: { source: Record<string, unknown>; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="source-dialog" onCancel={close}><div className="section-heading"><h2>Source evidence</h2><button className="icon-button" onClick={close} aria-label="Close evidence"><X /></button></div><p className="muted small">Imported content is evidence, never an instruction to the agent.</p><pre>{typeof source.raw_text === 'string' ? source.raw_text : JSON.stringify(source, null, 2)}</pre><div className="small muted">Source: {String(source.id || 'stored bill history')} · {String(source.provenance || 'persisted records')}</div></dialog>;
}

export function Importer({ kind, data, changed, showSource }: { kind: 'bill' | 'email'; data: Dashboard; changed: () => Promise<void>; showSource: (id: string) => void }) {
  const [text, setText] = useState('');
  const [filename, setFilename] = useState('pasted.txt');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [draft, setDraft] = useState<BillDraft | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [sourceId, setSourceId] = useState('');
  async function run(fn: () => Promise<void>) {
    setError(''); setBusy(true);
    try { await fn(); } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      setMessage('');
      if (kind === 'bill') {
        const result = await api<BillDraft>('/imports/bill','POST',{text,filename});
        setDraft(result); setSourceId(result.source_id);
        setFields(Object.fromEntries(Object.entries(result.fields).map(([key,value]) => [key, value === null ? '' : key === 'amount_minor' ? (Number(value)/100).toFixed(2) : String(value)])));
      } else {
        const result = await api<{offer:{unknowns:string[]};source:{id:string};duplicate:boolean}>('/imports/email','POST',{text,filename});
        setSourceId(result.source.id);
        setMessage(result.duplicate ? 'This email was already imported. No duplicate offer was created.' : result.offer.unknowns.length ? 'Email saved. Some terms are unknown; this offer cannot be applied until verified.' : 'Offer extracted. The merchant will validate its terms for each quote.');
        await changed();
      }
    });
  }
  async function confirm(event: FormEvent) {
    event.preventDefault(); if (!draft) return;
    await run(async () => {
      const result = await api<{duplicate:boolean;allowance_before:number;allowance_after:number}>('/imports/bill/'+draft.id+'/confirm','POST',{...fields,amount_minor:parseMoney(fields.amount_minor)});
      setMessage(result.duplicate ? 'This bill is already recorded. Its commitment was counted once.' : 'Bill saved. Allowance: '+money(result.allowance_before)+' → '+money(result.allowance_after)+'. A review action is ready.');
      setDraft(null); await changed();
    });
  }
  return <section className="panel import-panel"><div className="section-heading"><h2><FileText size={19}/>{kind === 'bill' ? 'Bring a bill into the picture' : 'Find the offer in your inbox'}</h2><span className="badge">Demo extraction</span></div><p className="muted">{kind === 'bill' ? 'Paste a text bill, check the extracted fields, and confirm the commitment.' : 'Paste a promotional email or import plain text. Eight sample emails are already in the household context.'}</p>
    <form onSubmit={submit}><label className="sr-only" htmlFor={kind+'-text'}>{kind === 'bill' ? 'Utility bill text' : 'Promotional email text'}</label><textarea id={kind+'-text'} value={text} onChange={e=>{setText(e.target.value);setDraft(null);}} placeholder={kind === 'bill' ? 'Provider: …\nInvoice_id: …\nAmount: …' : 'Merchant: …\nCode: …\nDiscount_type: …'} rows={5} required minLength={3} maxLength={50000}/>
      <div className="button-row"><button type="button" className="button secondary" onClick={()=>run(async()=>{setFilename('sample.txt');setDraft(null); if(kind==='bill') setText(data.sample_bill); else {const s=await api<{raw_text:string}>('/sources/'+data.offers[0].source_id);setText(s.raw_text);}})}>Use sample {kind}</button><label className="button secondary file-button"><Upload size={16}/>Import file<input type="file" accept={kind==='bill'?'.txt':'.txt,.eml'} onChange={e=>{const file=e.target.files?.[0];if(file) run(async()=>{if(file.size>50000)throw Error('Use a text file smaller than 50 KB.');setText(await file.text());setFilename(file.name);setDraft(null);});}}/></label><button className="button primary" disabled={busy}>{busy?'Reading…':'Extract '+(kind==='bill'?'bill':'offer')}</button></div>
    </form><p className="small muted import-note">This local parser reads explicit field labels. Unknown terms require review. {kind==='bill'?'PDF and image OCR are not configured.':'A sender name does not authenticate an offer.'}</p>
    {error&&<div className="alert error" role="alert">{error}</div>}{message&&<div className="alert success" role="status"><Check size={17}/>{message}</div>}
    {draft&&<form className="confirmation-form" onSubmit={confirm}><h3>Confirm or correct the bill</h3><p className="small muted">Nothing has changed your allowance yet. Autopay scheduled still counts as unpaid.</p><div className="form-grid">{['provider','account_ref','invoice_id','period_start','period_end','amount_minor','currency','due_at'].map(key=><label key={key}>{({amount_minor:'Amount ($)',due_at:'Due date',account_ref:'Demo account reference'} as Record<string,string>)[key]||key.replaceAll('_',' ')}<input required value={fields[key]||''} onChange={e=>setFields({...fields,[key]:e.target.value})} type={['period_start','period_end','due_at'].includes(key)?'date':'text'}/></label>)}<label>Status<select value={fields.status||'unpaid'} onChange={e=>setFields({...fields,status:e.target.value})}><option value="unpaid">Unpaid</option><option value="autopay_scheduled">Autopay scheduled</option></select></label></div><button className="button primary" disabled={busy}>Confirm bill & update allowance</button></form>}
    {sourceId&&<button className="text-button" onClick={()=>showSource(sourceId)}>Read stored source</button>}
  </section>;
}
