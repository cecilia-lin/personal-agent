import { AlertTriangle, Clock3, FileText, FlaskConical, ShieldCheck } from 'lucide-react';
import { label, type ClaimVerification as Verification, type EvidencePassage } from './api';

const states = {
  supported: { title: 'Required claim verified', tone: 'supported', Icon: ShieldCheck },
  conflict: { title: 'Required claim contradicted', tone: 'blocked', Icon: AlertTriangle },
  unsupported: { title: 'Required claim unsupported', tone: 'blocked', Icon: AlertTriangle },
  not_verifiable: { title: 'Required claim not verifiable', tone: 'blocked', Icon: AlertTriangle },
  pending: { title: 'Required claim pending', tone: 'pending', Icon: Clock3 },
  error: { title: 'Claim check unavailable', tone: 'blocked', Icon: AlertTriangle },
  not_required: { title: 'No required claim for this preference', tone: 'neutral', Icon: ShieldCheck },
  demo: { title: 'Demo claim check — not Senso', tone: 'demo', Icon: FlaskConical },
};

export function ClaimVerification({ verification, evidence = [], showRetrieval = true }: {
  verification?: Verification; evidence?: EvidencePassage[]; showRetrieval?: boolean;
}) {
  const display = verification && states[verification.state] || {
    title: 'Required claim not checked', tone: 'pending', Icon: Clock3,
  };
  const { Icon } = display;
  const sources = verification?.sources || [];
  const retrieved = evidence.some(source => source.provider === 'senso' || source.provenance === 'live');
  const verified = verification?.state === 'supported';
  return <section className="product-verification" aria-label="Product requirement verification">
    {showRetrieval && <div className="retrieval-state"><FileText size={15}/><div>
      <strong>{evidence.length ? retrieved ? 'Product information retrieved' : 'Sample product information' : 'No product information retrieved'}</strong>
      <span>{evidence.length ? `${evidence.length} passage${evidence.length === 1 ? '' : 's'} · ${retrieved ? 'Senso retrieval' : 'fixture evidence'}` : 'No retrieved passage is available.'}</span>
      <span>Retrieval alone does not verify the required claim.</span>
    </div></div>}
    <div className={'claim-state claim-' + display.tone}>
      <div className="claim-state-heading"><Icon size={17}/><strong>{display.title}</strong></div>
      <dl className="claim-facts"><div><dt>Requirement</dt><dd>{label(verification?.requirement || 'repairability')}</dd></div>
        <div><dt>Required feature</dt><dd>{verification?.feature ? label(verification.feature) : 'Precise feature not specified'}</dd></div></dl>
      {verification?.claim && <p className="claim-text">{verification.claim}</p>}
      <p className="claim-reason">{verification?.reason || 'This saved comparison has no required-claim check. Run Find options again before requesting a proposal.'}</p>
      {sources.map((source, index) => <blockquote key={`${source.content_id || source.source_id || 'passage'}-${index}`} className="claim-passage">
        <span>{verified ? 'Supporting passage' : 'Passage returned for this check'}</span>
        <p>{source.excerpt || source.chunk_text || 'No passage text returned.'}</p>
      </blockquote>)}
      {verification && <details className="claim-identifiers"><summary>Check record & evidence versions</summary>
        <dl><div><dt>Provider</dt><dd>{verification.provider || 'Not provided'} · {verification.provenance || 'unspecified provenance'}</dd></div>
          <div><dt>Check ID</dt><dd>{verification.check_id || 'No Senso check ID returned'}</dd></div>
          <div><dt>Product version checked</dt><dd>{verification.product_id} · {verification.product_version ?? 'not provided'}</dd></div>
          {verification.checked_at && <div><dt>Checked at</dt><dd><time dateTime={verification.checked_at}>{new Date(verification.checked_at).toLocaleString()}</time></dd></div>}
          {sources.map((source, index) => <div key={index}><dt>Evidence {index + 1}</dt><dd>Source {source.content_id || source.source_id || 'not provided'}<br/>Version {source.version_id || source.source_version || 'not provided'}{source.kb_node_id && <><br/>Knowledge node {source.kb_node_id}</>}</dd></div>)}
          {verification.evidence_fingerprint && <div><dt>Evidence fingerprint</dt><dd>{verification.evidence_fingerprint}</dd></div>}
        </dl>
      </details>}
    </div>
  </section>;
}
