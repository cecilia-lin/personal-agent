import { useState } from 'react';
import { Clock3, Database, FileText, FlaskConical, LoaderCircle } from 'lucide-react';
import { api } from './api';

type Passage = {
  passage: string;
  content_id?: string | null;
  content_chunk_id?: string | null;
  version_id?: string | null;
};
type ResearchCandidate = {
  product_id: string;
  title: string;
  return_policy: string | null;
  requirement_state: 'supported' | 'contradicted' | 'unknown';
  policy_eligible: boolean;
  reason: string;
  passages: Passage[];
  decision: 'Wait';
  proposal_allowed: false;
};
type RecallResult = {
  state: 'ready' | 'pending' | 'blocked';
  reason: string;
  synthetic_demo: true;
  research_only: true;
  proposal_allowed: false;
  persona_id?: string;
  session_id?: string;
  requirement?: {
    text: string;
    kind: 'minimum_return_window_days';
    value: number;
    source: 'cognee_graph';
    source_ids: string[];
  };
  candidates: ResearchCandidate[];
};

const requirementLabels = {
  supported: 'Required return window supported',
  contradicted: 'Conflicts with the required return window',
  unknown: 'Required return window unresolved',
};

export function ResearchMemory() {
  const [result, setResult] = useState<RecallResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function recall() {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const response = await api<RecallResult>('/research-memory/recall', 'POST', {});
      if (!['ready', 'pending', 'blocked'].includes(response.state) ||
          response.synthetic_demo !== true || response.research_only !== true ||
          response.proposal_allowed !== false) {
        throw new Error('The prepared research response could not be validated. No proposal is available.');
      }
      setResult(response);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Prepared memory is unavailable. Try again later.');
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel research-memory" aria-labelledby="research-memory-title">
    <div className="section-heading">
      <h2 id="research-memory-title"><Database size={19}/>A remembered requirement</h2>
      <span className="badge demo"><FlaskConical size={12}/>Synthetic research</span>
    </div>
    <p className="muted small">Recall a prepared demo persona’s requirement in a new session, then compare it with current Senso evidence from the sample catalog.</p>
    <button className="button secondary" onClick={recall} disabled={busy}>
      {busy ? <LoaderCircle className="spin" size={16}/> : <Database size={16}/>}
      {busy ? 'Recalling prepared memory…' : 'Recall prepared demo memory'}
    </button>
    {busy && <p className="verification-progress" role="status">Checking graph memory and product evidence. Research products cannot become purchase proposals.</p>}
    {error && <p className="alert error" role="alert">{error}</p>}
    {result && <div className="research-memory-result" aria-live="polite">
      <div className={'claim-state claim-' + (result.state === 'ready' ? 'neutral' : 'pending')}>
        <strong>{result.state === 'ready' ? 'Memory and evidence comparison complete' : result.state === 'pending' ? 'Prepared memory is pending' : 'Prepared memory is blocked'}</strong>
        <p className="claim-reason">{result.reason}</p>
      </div>
      {result.requirement && <div className="research-requirement">
        <strong>Confirmed requirement recalled from Cognee</strong>
        <p>{result.requirement.text}</p>
        <details className="claim-identifiers"><summary>Memory source</summary>
          <dl><div><dt>Demo persona</dt><dd>{result.persona_id || 'Not returned'}</dd></div>
            <div><dt>New session</dt><dd>{result.session_id || 'Not returned'}</dd></div>
            <div><dt>Graph source IDs</dt><dd>{result.requirement.source_ids.length ? result.requirement.source_ids.join(', ') : 'No source IDs returned'}</dd></div>
          </dl>
        </details>
      </div>}
      <div className="research-candidates">{(result.candidates || []).map(candidate => <article className="research-candidate" key={candidate.product_id}>
        <h3>{candidate.title}</h3>
        <p className="small muted">Sample policy: {candidate.return_policy || 'Not stated'}</p>
        <div className="retrieval-state"><FileText size={15}/><div>
          <strong>{candidate.passages.length ? 'Product information retrieved' : 'No supporting passage retrieved'}</strong>
          <span>{candidate.passages.length} Senso passage{candidate.passages.length === 1 ? '' : 's'} · retrieval is separate from the requirement check.</span>
        </div></div>
        <div className={'claim-state claim-' + (candidate.requirement_state === 'supported' && candidate.policy_eligible ? 'supported' : 'blocked')}>
          <strong>{requirementLabels[candidate.requirement_state] || requirementLabels.unknown}</strong>
          <p className="claim-reason">{candidate.reason}</p>
          {candidate.passages.map((passage, index) => <blockquote className="claim-passage" key={`${passage.content_chunk_id || 'passage'}-${index}`}>
            <span>Senso passage</span><p>{passage.passage}</p>
            <details className="claim-identifiers"><summary>Evidence version</summary>
              <dl><div><dt>Content</dt><dd>{passage.content_id || 'Not returned'}</dd></div>
                <div><dt>Chunk</dt><dd>{passage.content_chunk_id || 'Not returned'}</dd></div>
                <div><dt>Version</dt><dd>{passage.version_id || 'Not returned'}</dd></div>
              </dl>
            </details>
          </blockquote>)}
        </div>
        <p className="research-wait"><Clock3 size={14}/>Wait · research only</p>
      </article>)}</div>
      <button className="button secondary full" disabled>Purchase proposal unavailable for research products</button>
      <p className="small muted">Sample prices are observations, not executable merchant quotes. This isolated demonstration does not change your household preferences, budget, approvals or cart.</p>
    </div>}
  </section>;
}
