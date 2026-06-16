import { useEffect, useMemo, useState } from 'react';
import katex from 'katex';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import 'katex/dist/katex.min.css';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

function resolveApiUrl(path) {
  if (!path) return '#';
  try {
    return new URL(path, API_BASE).href;
  } catch {
    return path;
  }
}

const mapListItem = (item) => ({
  id: item.question_id,
  title: item.question_text?.slice(0, 120) ?? 'Untitled',
  year: item.year,
  topic: item.topic,
  difficulty: item.difficulty ?? 'Medium',
  importance: item.importance_score ?? 0,
  accuracy: item.confidence ?? 0,
  tags: item.semantic_tags_json ?? [],
  summary: item.question_text?.slice(0, 220) ?? '',
});

const questionAnalytics = [
  { label: 'PYQs indexed', value: '1,248' },
  { label: 'High importance', value: '312' },
  { label: 'Average accuracy', value: '82%' },
  { label: 'Agent-ready topics', value: '47' },
];

const shellCard =
  'relative overflow-visible rounded-[32px] border border-white/10 bg-[#171a1f]/92 shadow-[0_28px_84px_rgba(0,0,0,0.35)]';
const sectionCard =
  'relative rounded-[26px] border border-white/10 bg-[#1a1d22]/92 shadow-[0_14px_28px_rgba(0,0,0,0.22)]';
const insetCard =
  'rounded-[22px] border border-white/10 bg-[#20242b]/92 shadow-[0_12px_24px_rgba(0,0,0,0.18)]';

function escapeHtml(text) {
  return String(text)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderMathExpression(expression, displayMode) {
  try {
    return katex.renderToString(expression.trim(), {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
      output: 'html',
    });
  } catch {
    return `<code>${escapeHtml(displayMode ? `$$${expression}$$` : `$${expression}$`)}</code>`;
  }
}

function renderTechnicalMarkdown(source) {
  const raw = String(source ?? '');
  const blockPlaceholderPrefix = '__KATEX_BLOCK_';
  const inlinePlaceholderPrefix = '__KATEX_INLINE_';
  const placeholders = new Map();

  let working = raw.replace(/\$\$([\s\S]+?)\$\$/g, (_match, expression) => {
    const token = `${blockPlaceholderPrefix}${placeholders.size}__`;
    placeholders.set(token, renderMathExpression(expression, true));
    return token;
  });

  working = working.replace(/(?<!\\)\$([^\n$]+?)\$/g, (_match, expression) => {
    const token = `${inlinePlaceholderPrefix}${placeholders.size}__`;
    placeholders.set(token, renderMathExpression(expression, false));
    return token;
  });

  const html = marked.parse(working, {
    gfm: true,
    breaks: true,
  });

  const withMath = Array.from(placeholders.entries()).reduce(
    (acc, [token, htmlFragment]) => acc.split(token).join(htmlFragment),
    html,
  );

  return DOMPurify.sanitize(withMath, { ADD_ATTR: ['style'] });
}

function Pill({ children }) {
  return (
    <span className="inline-flex items-center rounded-full border border-amber-500/15 bg-amber-50/8 px-3 py-1 text-[0.78rem] tracking-[0.04em] text-amber-100/90">
      {children}
    </span>
  );
}

function MetricCard({ label, value }) {
  return (
    <article className={`${insetCard} p-4`}>
      <div className="mb-2 text-[0.72rem] uppercase tracking-[0.22em] text-slate-400">{label}</div>
      <div className="text-2xl font-semibold tracking-[-0.03em] text-[#f5efe6]">{value}</div>
    </article>
  );
}

function TabButton({ active, children, onClick }) {
  return (
    <button
      className={`rounded-full border px-4 py-2.5 text-sm tracking-[0.04em] transition duration-150 ease-out ${
        active
          ? 'border-amber-400/30 bg-amber-400/10 text-[#f7efe1] shadow-[0_8px_20px_rgba(0,0,0,0.18)]'
          : 'border-white/10 bg-white/3 text-slate-300 hover:-translate-y-px hover:border-amber-400/20 hover:bg-white/6 hover:text-[#f7efe1]'
      }`}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

function QuestionCard({ question, selected, onSelect }) {
  return (
    <button
      className={`group w-full rounded-[22px] border p-4 text-left transition duration-150 ease-out ${
        selected
          ? 'border-amber-400/30 bg-amber-50/8 shadow-[0_18px_32px_rgba(0,0,0,0.18)]'
          : 'border-white/10 bg-[#20242b]/85 hover:-translate-y-px hover:border-amber-400/20 hover:bg-[#242932]/90'
      }`}
      onClick={onSelect}
      type="button"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-400">
        <span className="font-medium tracking-[0.12em] text-amber-100/80">{question.year}</span>
        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[0.72rem] uppercase tracking-[0.18em] text-slate-300">
          {question.difficulty}
        </span>
      </div>
      <h3 className="mt-4 text-[1.06rem] font-semibold tracking-[-0.02em] text-[#f5efe6]">{question.title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-300/80">{question.summary}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {question.tags.map((tag) => (
          <Pill key={tag}>{tag}</Pill>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-white/8 pt-4 text-sm text-slate-400">
        <span>{question.topic}</span>
        <span className="font-medium text-amber-100/80">Importance {Math.round(question.importance * 100)}%</span>
      </div>
    </button>
  );
}

function DetailPanel({ question }) {
  if (!question) {
    return (
      <aside className={`lg:sticky ${sectionCard} lg:top-6 p-6`}>
        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Selected question</div>
        <h2 className="mt-3 text-[1.55rem] font-semibold tracking-[-0.03em] text-[#f5efe6]">Select a question</h2>
        <p className="mt-4 text-sm leading-7 text-slate-300/80">Choose a question from the archive list to inspect detail, download the source PDF, and review the attached signals.</p>
      </aside>
    );
  }

  return (
    <aside className={`${sectionCard} lg:sticky top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto thin-scrollbar lg:pr-2 p-6`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Selected question</div>
          <h2 className="mt-3 text-xl font-semibold tracking-[-0.03em] text-[#f5efe6]">{question.title}</h2>
        </div>
        <a
          className="inline-flex items-center rounded-full border border-amber-400/20 bg-amber-400/10 px-4 py-2 text-sm font-medium tracking-[0.04em] text-amber-100 transition duration-150 ease-out hover:-translate-y-px hover:border-amber-400/30 hover:bg-amber-400/15"
          href={resolveApiUrl(question?.download_url)}
          target="_blank"
          rel="noreferrer"
          title="Download full PDF"
        >
          Download PDF
        </a>
      </div>

      {/* <p className="mt-4 text-sm leading-7 text-slate-300/80">{question.summary}</p> */}

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <MetricCard label="Importance" value={`${Math.round((question?.importance ?? 0) * 100)}%`} />
        <MetricCard label="Accuracy" value={`${Math.round((question?.accuracy ?? 0) * 100)}%`} />
        <MetricCard label="Concept depth" value={`${Math.round(((question?.analytics?.conceptDepth) ?? 0) * 100)}%`} />
        <MetricCard label="Similar questions" value={String((question?.analytics?.similarQuestions) ?? 0)} />
      </div>

      <div className="mt-6 rounded-[20px] border border-white/10 bg-black/10 p-4">
        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Tags</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {question.tags.map((tag) => (
            <Pill key={tag}>{tag}</Pill>
          ))}
        </div>
      </div>

      <div className="mt-6 rounded-[20px] border border-white/10 bg-black/10 p-4">
        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Agent notes</div>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-7 text-slate-300/80">
          <li>Likely to reappear in computer networks exams.</li>
          <li>Good candidate for spaced review and quick drills.</li>
          <li>Use the agent tab to ask for related topics or explanations.</li>
        </ul>
      </div>
    </aside>
  );
}

function DashboardTab({ pyqs, selectedQuestion, onSelectQuestion }) {
  return (
    <section className="grid gap-5 lg:grid-cols-[1.18fr_0.82fr] lg:items-start">
      <div className={`${sectionCard} p-6`}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">PYQs</div>
            <h2 className="mt-3 text-[1.55rem] font-semibold tracking-[-0.03em] text-[#f5efe6]">Recent questions</h2>
          </div>
          <span className="rounded-full border border-amber-400/20 bg-amber-400/10 px-3 py-1 text-[0.72rem] uppercase tracking-[0.18em] text-amber-100/80">
            {pyqs.length} items
          </span>
        </div>

        <div className="mt-5 grid gap-4">
          {pyqs.map((question) => (
            <QuestionCard
              key={question.id}
              question={question}
              selected={selectedQuestion && question.id === selectedQuestion.id}
              onSelect={() => onSelectQuestion(question.id)}
            />
          ))}
        </div>
      </div>

      <div className="self-start h-full lg:relative lg:top-0">
        <DetailPanel question={selectedQuestion} />
      </div>
    </section>
  );
}

function PaginationControls({ page, totalPages, totalItems, canNext, onPrevious, onNext }) {
  return (
    <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-[20px] border border-white/10 bg-black/10 px-4 py-3 text-sm text-slate-300/80">
      <div>
        Page <span className="text-amber-100/80">{page}</span> of <span className="text-amber-100/80">{totalPages}</span> · <span className="text-amber-100/80">{totalItems}</span> items
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm tracking-[0.04em] text-slate-300 transition duration-150 ease-out hover:-translate-y-px hover:border-amber-400/20 hover:bg-white/7 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          onClick={onPrevious}
          disabled={page <= 1}
        >
          Previous
        </button>
        <button
          className="rounded-full border border-amber-400/20 bg-amber-400/10 px-4 py-2 text-sm tracking-[0.04em] text-amber-100 transition duration-150 ease-out hover:-translate-y-px hover:border-amber-400/30 hover:bg-amber-400/15 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          onClick={onNext}
          disabled={!canNext}
        >
          Next
        </button>
      </div>
    </div>
  );
}

function AnalyticsTab({ summary }) {
  const overview = summary?.overview ?? {};
  const topTopics = summary?.top_topics ?? [];
  const difficultyBreakdown = summary?.difficulty_breakdown ?? [];
  const metrics = summary
    ? [
        { label: 'Questions indexed', value: String(overview.total_questions ?? '—') },
        { label: 'Distinct topics', value: String(overview.total_topics ?? '—') },
        { label: 'Avg importance', value: `${Math.round((Number(overview.average_importance ?? 0)) * 100)}%` },
        { label: 'Avg confidence', value: `${Math.round((Number(overview.average_confidence ?? 0)) * 100)}%` },
      ]
    : questionAnalytics;

  return (
    <section className="grid gap-5 lg:grid-cols-[1fr_0.84fr]">
      <div className={`${sectionCard} p-6`}>
        <div>
          <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Analytics</div>
          <h2 className="mt-3 text-[1.55rem] font-semibold tracking-[-0.03em] text-[#f5efe6]">Study signals and topic trends</h2>
          <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300/80">Live aggregations from the backend are shown here when available. The layout is intentionally restrained: editorial, instrument-like, and quiet.</p>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <MetricCard key={metric.label} label={metric.label} value={metric.value} />
          ))}
        </div>

        <div className="mt-6 rounded-[22px] border border-white/10 bg-black/10 p-5">
          <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Chart placeholder</div>
          <h3 className="mt-3 text-[1.25rem] font-semibold tracking-[-0.02em] text-[#f5efe6]">Importance by topic</h3>
          <div className="mt-6 grid gap-4">
            {(topTopics.length ? topTopics : [
              { topic: 'No data yet', average_importance: 0, question_count: 0 },
            ]).map((item) => {
              const width = `${Math.max(8, Math.round(Number(item.average_importance ?? 0) * 100))}%`;
              return (
                <div key={item.topic} className="grid gap-2 text-sm text-slate-300/80">
                  <div className="flex items-center justify-between gap-4">
                    <span>{item.topic}</span>
                    <span className="text-amber-100/80">
                      {Math.round(Number(item.average_importance ?? 0) * 100)}% · {item.question_count ?? 0}
                    </span>
                  </div>
                  <div className="h-3 rounded-full border border-white/8 bg-white/5">
                    <div
                      className="h-full rounded-full bg-[linear-gradient(90deg,rgba(245,158,11,0.42),rgba(148,163,184,0.22))]"
                      style={{ width }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="mt-6 rounded-[22px] border border-white/10 bg-black/10 p-5">
          <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Difficulty breakdown</div>
          <div className="mt-4 grid gap-3">
            {(difficultyBreakdown.length ? difficultyBreakdown : [{ difficulty: 'No data yet', question_count: 0 }]).map((item) => (
              <div key={item.difficulty} className="flex items-center justify-between rounded-[16px] border border-white/8 bg-[#20242b]/88 px-4 py-3 text-sm text-slate-300/80">
                <span>{item.difficulty}</span>
                <span className="text-amber-100/80">{item.question_count ?? 0}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <aside className={`${sectionCard} p-6`}>
        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Signals</div>
        <div className="mt-3 grid gap-4">
          <MetricCard label="Peak topic" value={topTopics[0]?.topic ?? '—'} />
          <MetricCard label="Top importance" value={topTopics[0] ? `${Math.round(Number(topTopics[0].average_importance ?? 0) * 100)}%` : '—'} />
        </div>
        <div className="mt-6 rounded-[22px] border border-white/10 bg-black/10 p-5">
          <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Observations</div>
          <p className="mt-3 text-sm leading-7 text-slate-300/80">These cards now render the actual backend summary payload instead of placeholder values, so the page will show live analytics when the API returns data.</p>
        </div>
      </aside>
    </section>
  );
}

function AgentTab({ selectedQuestion }) {
  const starterPrompts = [
    'Explain this PYQ in simple terms.',
    'Find related PYQs for this topic.',
    'Summarize the weak areas for revision.',
  ];
  const [prompt, setPrompt] = useState('');
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [agentResult, setAgentResult] = useState(null);
  const [showSql, setShowSql] = useState(false);

  const askAgent = async () => {
    if (!prompt) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/agent/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, question_id: selectedQuestion?.id }),
      });
      const contentType = res.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        const data = await res.json();
        setAgentResult(data);
        setResponse(data.answer ?? JSON.stringify(data, null, 2));
      } else if (res.body && res.body.getReader) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let done = false;
        let acc = '';
        while (!done) {
          // eslint-disable-next-line no-await-in-loop
          const { value, done: d } = await reader.read();
          done = d;
          if (value) {
            const chunk = decoder.decode(value, { stream: true });
            acc += chunk;
            setResponse(acc);
          }
        }
        setAgentResult(null);
      } else {
        const text = await res.text();
        setResponse(text);
      }
    } catch (err) {
      setResponse(`Error: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const renderedHtml = useMemo(() => {
    if (!response) return null;
    return renderTechnicalMarkdown(response);
  }, [response]);

  const notesHtml = useMemo(() => {
    if (!agentResult?.notes) return null;
    return renderTechnicalMarkdown(agentResult.notes);
  }, [agentResult]);

  return (
    <section className="grid gap-5 lg:grid-cols-[1fr_0.84fr]">
      <div className={`${sectionCard} p-6`}>
        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Agent</div>
        <h2 className="mt-3 text-[1.55rem] font-semibold tracking-[-0.03em] text-[#f5efe6]">Ask the exam agent</h2>
        <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300/80">Use the agent to explain questions, surface related PYQs, or synthesize revision advice. The output is rendered like an annotated research note with math support for technical expressions.</p>

        <label className="mt-6 block text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70" htmlFor="agent-prompt">
          Prompt
        </label>
        <textarea
          id="agent-prompt"
          className="mt-3 min-h-44 w-full rounded-[22px] border border-white/10 bg-[#20242b]/92 px-4 py-4 text-sm leading-7 text-[#f5efe6] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] outline-none transition duration-150 placeholder:text-slate-500 focus:border-amber-400/30 focus:ring-2 focus:ring-amber-400/10"
          placeholder={selectedQuestion ? `Ask about: ${selectedQuestion.title}` : 'Ask a question...'}
          rows={6}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />

        <div className="mt-4 flex flex-wrap gap-3">
          <button
            className="inline-flex items-center justify-center rounded-full border border-amber-400/20 bg-amber-400/10 px-4 py-2.5 text-sm font-medium tracking-[0.04em] text-amber-100 transition duration-150 ease-out hover:-translate-y-px hover:border-amber-400/30 hover:bg-amber-400/15 disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
            onClick={askAgent}
            disabled={loading}
          >
            {loading ? 'Thinking…' : 'Ask agent'}
          </button>
          <button
            className="inline-flex items-center justify-center rounded-full border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium tracking-[0.04em] text-slate-300 transition duration-150 ease-out hover:-translate-y-px hover:border-white/15 hover:bg-white/7"
            type="button"
            onClick={() => {
              setPrompt('');
              setResponse(null);
              setAgentResult(null);
              setShowSql(false);
            }}
          >
            Clear
          </button>
        </div>

        {response && (
          <div className="mt-6 space-y-4 border-t border-white/8 pt-5">
            <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Agent response</div>
            {renderedHtml ? (
              <div
                className="prose prose-invert max-w-none rounded-[22px] border border-white/10 bg-[#20242b]/88 p-5 text-slate-200 prose-headings:text-[#f7efe1] prose-strong:text-[#fff8ef] prose-code:rounded prose-code:bg-black/25 prose-code:px-1.5 prose-code:py-0.5 prose-code:text-amber-100 prose-pre:bg-black/20 prose-blockquote:border-amber-400/25 prose-blockquote:text-slate-300"
                dangerouslySetInnerHTML={{ __html: renderedHtml }}
              />
            ) : (
              <pre className="overflow-auto rounded-[22px] border border-white/10 bg-[#20242b]/88 p-5 text-sm leading-7 text-slate-200">
                {response}
              </pre>
            )}

            {agentResult && (
              <div className="rounded-[22px] border border-white/10 bg-black/10 p-4">
                <button
                  className="inline-flex items-center justify-center rounded-full border border-amber-400/20 bg-amber-400/10 px-4 py-2 text-sm font-medium tracking-[0.04em] text-amber-100 transition duration-150 ease-out hover:-translate-y-px hover:border-amber-400/30 hover:bg-amber-400/15"
                  type="button"
                  onClick={() => setShowSql((s) => !s)}
                >
                  {showSql ? 'Hide SQL & Notes' : 'Show SQL & Notes'}
                </button>
                {showSql && (
                  <div className="mt-4 grid gap-4">
                    {agentResult.sql && (
                      <div>
                        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Draft SQL</div>
                        <pre className="mt-3 overflow-auto rounded-[18px] border border-white/10 bg-[#20242b]/88 p-4 text-sm leading-7 text-slate-200">
                          <code>{agentResult.sql}</code>
                        </pre>
                      </div>
                    )}
                    {agentResult.notes && (
                      <div>
                        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Agent notes</div>
                        {notesHtml ? (
                          <div
                            className="prose prose-invert mt-3 max-w-none rounded-[18px] border border-white/10 bg-[#20242b]/88 p-4 text-slate-200 prose-headings:text-[#f7efe1] prose-strong:text-[#fff8ef] prose-code:rounded prose-code:bg-black/25 prose-code:px-1.5 prose-code:py-0.5 prose-code:text-amber-100 prose-pre:bg-black/20"
                            dangerouslySetInnerHTML={{ __html: notesHtml }}
                          />
                        ) : (
                          <pre className="mt-3 overflow-auto rounded-[18px] border border-white/10 bg-[#20242b]/88 p-4 text-sm leading-7 text-slate-200">
                            {agentResult.notes}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <aside className={`${sectionCard} p-6`}>
        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Suggested prompts</div>
        <div className="mt-4 grid gap-3">
          {starterPrompts.map((p) => (
            <button
              key={p}
              className="w-full rounded-[18px] border border-white/10 bg-[#20242b]/88 px-4 py-4 text-left text-sm leading-7 text-slate-200 transition duration-150 ease-out hover:-translate-y-px hover:border-amber-400/20 hover:bg-[#242932]/90"
              type="button"
              onClick={() => setPrompt(p)}
            >
              {p}
            </button>
          ))}
        </div>
      </aside>
    </section>
  );
}

function IngestionTab() {
  const [pyqFiles, setPyqFiles] = useState([]);
  const [textbookFiles, setTextbookFiles] = useState([]);
  const [sourceKind, setSourceKind] = useState('pyq');
  const [subject, setSubject] = useState('Computer Networks');
  const [publicationYear, setPublicationYear] = useState('');
  const [coverageStartYear, setCoverageStartYear] = useState('');
  const [coverageEndYear, setCoverageEndYear] = useState('');
  const [ownerUserId, setOwnerUserId] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadLog, setUploadLog] = useState([]);

  const fileLineClass = 'flex items-center justify-between gap-3 rounded-[16px] border border-white/8 bg-black/10 px-4 py-3 text-sm text-slate-300/80';

  const selectedFiles = sourceKind === 'textbook' ? textbookFiles : pyqFiles;

  const addLog = (message) => {
    setUploadLog((current) => [{ id: crypto.randomUUID(), message, time: new Date().toLocaleTimeString() }, ...current].slice(0, 8));
  };

  const uploadSelectedFiles = async () => {
    if (!selectedFiles.length || isUploading) return;

    setIsUploading(true);
    try {
      for (const file of selectedFiles) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('source_kind', sourceKind);
        formData.append('source_subtype', sourceKind === 'textbook' ? 'reference' : 'exam-paper');
        formData.append('subject', subject);
        if (publicationYear) formData.append('publication_year', publicationYear);
        if (coverageStartYear) formData.append('coverage_start_year', coverageStartYear);
        if (coverageEndYear) formData.append('coverage_end_year', coverageEndYear);
        formData.append('coverage_years_json', JSON.stringify([]));
        if (ownerUserId) formData.append('owner_user_id', ownerUserId);

        const response = await fetch(`${API_BASE}/ingest/upload`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(errorText || `Upload failed for ${file.name}`);
        }

        const result = await response.json();
        addLog(`Queued ${file.name} -> source ${result.source_id} | OCR job ${result.queued_job_id}`);
      }
    } catch (err) {
      addLog(`Upload error: ${String(err)}`);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <section className="grid gap-5 lg:grid-cols-[1fr_0.84fr]">
      <div className={`${sectionCard} p-6`}>
        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Ingestion desk</div>
        <h2 className="mt-3 text-[1.55rem] font-semibold tracking-[-0.03em] text-[#f5efe6]">Upload PYQs and textbooks</h2>
        <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300/80">This section is for staging files before the backend ingest flow is wired up. You can queue PDFs now and we’ll connect the upload path later.</p>

        <div className="mt-6 grid gap-5 xl:grid-cols-2">
          <div className={`${insetCard} p-5`}>
            <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">PYQ archive</div>
            <h3 className="mt-3 text-[1.15rem] font-semibold tracking-[-0.02em] text-[#f5efe6]">Upload previous year questions</h3>
            <p className="mt-2 text-sm leading-7 text-slate-300/80">PDFs, scans, or bundled paper sets. Files are queued to the backend ingest pipeline and split into two-page Azure OCR batches automatically.</p>

            <label className="mt-4 flex cursor-pointer flex-col gap-3 rounded-[20px] border border-dashed border-amber-400/20 bg-amber-400/6 p-4 text-sm text-slate-300/85 transition hover:border-amber-400/30 hover:bg-amber-400/10">
              <span className="text-[0.72rem] uppercase tracking-[0.24em] text-amber-100/70">Choose PYQ files</span>
              <span>Drop PDFs or click to browse the archive</span>
              <input
                className="hidden"
                type="file"
                accept="application/pdf"
                multiple
                onChange={(event) => setPyqFiles(Array.from(event.target.files ?? []))}
              />
            </label>

            <div className="mt-4 grid gap-2">
              {pyqFiles.length ? pyqFiles.map((file) => (
                <div key={file.name} className={fileLineClass}>
                  <span className="truncate">{file.name}</span>
                  <span className="rounded-full border border-white/10 px-2 py-1 text-[0.7rem] uppercase tracking-[0.18em] text-amber-100/70">
                    {Math.max(1, Math.round(file.size / 1024))} KB
                  </span>
                </div>
              )) : (
                <div className={fileLineClass}>No PYQ files selected yet.</div>
              )}
            </div>
          </div>

          <div className={`${insetCard} p-5`}>
            <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Textbook vault</div>
            <h3 className="mt-3 text-[1.15rem] font-semibold tracking-[-0.02em] text-[#f5efe6]">Upload reference textbooks</h3>
            <p className="mt-2 text-sm leading-7 text-slate-300/80">Reference chapters, extracted reading packs, or scanned textbook pages. These go through the same upload pipeline and Azure will only process them in 2-page batches.</p>

            <label className="mt-4 flex cursor-pointer flex-col gap-3 rounded-[20px] border border-dashed border-amber-400/20 bg-amber-400/6 p-4 text-sm text-slate-300/85 transition hover:border-amber-400/30 hover:bg-amber-400/10">
              <span className="text-[0.72rem] uppercase tracking-[0.24em] text-amber-100/70">Choose textbook files</span>
              <span>Upload one or many PDFs for later indexing</span>
              <input
                className="hidden"
                type="file"
                accept="application/pdf"
                multiple
                onChange={(event) => setTextbookFiles(Array.from(event.target.files ?? []))}
              />
            </label>

            <div className="mt-4 grid gap-2">
              {textbookFiles.length ? textbookFiles.map((file) => (
                <div key={file.name} className={fileLineClass}>
                  <span className="truncate">{file.name}</span>
                  <span className="rounded-full border border-white/10 px-2 py-1 text-[0.7rem] uppercase tracking-[0.18em] text-amber-100/70">
                    {Math.max(1, Math.round(file.size / 1024))} KB
                  </span>
                </div>
              )) : (
                <div className={fileLineClass}>No textbook files selected yet.</div>
              )}
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-[22px] border border-white/10 bg-black/10 p-5">
          <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Upload metadata</div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <label className="grid gap-2 text-sm text-slate-300/80">
              Source kind
              <select
                className="rounded-[16px] border border-white/10 bg-[#20242b]/92 px-4 py-3 text-[#f5efe6] outline-none focus:border-amber-400/30"
                value={sourceKind}
                onChange={(event) => setSourceKind(event.target.value)}
              >
                <option value="pyq">PYQ</option>
                <option value="textbook">Textbook</option>
              </select>
            </label>
            <label className="grid gap-2 text-sm text-slate-300/80">
              Subject
              <input
                className="rounded-[16px] border border-white/10 bg-[#20242b]/92 px-4 py-3 text-[#f5efe6] outline-none focus:border-amber-400/30"
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-300/80">
              Publication year
              <input
                className="rounded-[16px] border border-white/10 bg-[#20242b]/92 px-4 py-3 text-[#f5efe6] outline-none focus:border-amber-400/30"
                value={publicationYear}
                onChange={(event) => setPublicationYear(event.target.value)}
                placeholder="e.g. 2024"
                inputMode="numeric"
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-300/80">
              Owner user ID
              <input
                className="rounded-[16px] border border-white/10 bg-[#20242b]/92 px-4 py-3 text-[#f5efe6] outline-none focus:border-amber-400/30"
                value={ownerUserId}
                onChange={(event) => setOwnerUserId(event.target.value)}
                placeholder="optional"
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-300/80">
              Coverage start year
              <input
                className="rounded-[16px] border border-white/10 bg-[#20242b]/92 px-4 py-3 text-[#f5efe6] outline-none focus:border-amber-400/30"
                value={coverageStartYear}
                onChange={(event) => setCoverageStartYear(event.target.value)}
                placeholder="optional"
                inputMode="numeric"
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-300/80">
              Coverage end year
              <input
                className="rounded-[16px] border border-white/10 bg-[#20242b]/92 px-4 py-3 text-[#f5efe6] outline-none focus:border-amber-400/30"
                value={coverageEndYear}
                onChange={(event) => setCoverageEndYear(event.target.value)}
                placeholder="optional"
                inputMode="numeric"
              />
            </label>
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            <button
              className="inline-flex items-center justify-center rounded-full border border-amber-400/20 bg-amber-400/10 px-4 py-2.5 text-sm font-medium tracking-[0.04em] text-amber-100 transition duration-150 ease-out hover:-translate-y-px hover:border-amber-400/30 hover:bg-amber-400/15 disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              onClick={uploadSelectedFiles}
              disabled={!selectedFiles.length || isUploading}
            >
              {isUploading ? 'Queueing to backend…' : 'Upload to pipeline'}
            </button>
            <button
              className="inline-flex items-center justify-center rounded-full border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium tracking-[0.04em] text-slate-300 transition duration-150 ease-out hover:-translate-y-px hover:border-white/15 hover:bg-white/7"
              type="button"
              onClick={() => {
                setPyqFiles([]);
                setTextbookFiles([]);
                setUploadLog([]);
              }}
            >
              Clear queue
            </button>
          </div>
        </div>
      </div>

      <aside className={`${sectionCard} p-6`}>
        <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Staging notes</div>
        <div className="mt-4 grid gap-4">
          <MetricCard label="PYQ files queued" value={String(pyqFiles.length)} />
          <MetricCard label="Textbook files queued" value={String(textbookFiles.length)} />
          <MetricCard label="Target queue" value={sourceKind === 'textbook' ? 'Textbooks' : 'PYQs'} />
        </div>
        <div className="mt-6 rounded-[22px] border border-white/10 bg-black/10 p-5">
          <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Next step</div>
          <p className="mt-3 text-sm leading-7 text-slate-300/80">Once the backend ingestion endpoint is ready, this tab can pass the selected files into the pipeline without changing the visual structure.</p>
        </div>

        <div className="mt-6 rounded-[22px] border border-white/10 bg-black/10 p-5">
          <div className="text-[0.72rem] uppercase tracking-[0.26em] text-amber-100/70">Pipeline log</div>
          <div className="mt-3 grid gap-2">
            {uploadLog.length ? uploadLog.map((entry) => (
              <div key={entry.id} className="rounded-[16px] border border-white/8 bg-[#20242b]/88 px-4 py-3 text-sm leading-6 text-slate-300/80">
                <div className="text-[0.72rem] uppercase tracking-[0.18em] text-amber-100/70">{entry.time}</div>
                <div className="mt-1">{entry.message}</div>
              </div>
            )) : (
              <div className={fileLineClass}>Uploads will appear here once queued.</div>
            )}
          </div>
        </div>
      </aside>
    </section>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [pyqs, setPyqs] = useState([]);
  const [selectedQuestion, setSelectedQuestion] = useState(null);
  const [analyticsSummary, setAnalyticsSummary] = useState(null);
  const [questionPage, setQuestionPage] = useState(1);
  const [questionPageSize] = useState(12);
  const [questionTotalPages, setQuestionTotalPages] = useState(1);
  const [questionTotalItems, setQuestionTotalItems] = useState(0);
  const [questionHasNext, setQuestionHasNext] = useState(false);
  const [isLoadingQuestions, setIsLoadingQuestions] = useState(false);
  const effectiveTotalPages = Math.max(1, questionTotalPages, Math.ceil(questionTotalItems / questionPageSize));
  const effectiveHasNext = questionHasNext || questionPage * questionPageSize < questionTotalItems;

  useEffect(() => {
    let cancelled = false;

    const fetchPyqs = async () => {
      setIsLoadingQuestions(true);
      try {
        const offset = (questionPage - 1) * questionPageSize;
        const res = await fetch(`${API_BASE}/api/pyqs?limit=${questionPageSize}&offset=${offset}`);
        const data = await res.json();
        const list = (data.items || []).map(mapListItem);
        if (cancelled) return;
        setPyqs(list);
        setQuestionTotalItems(data.total ?? 0);
        setQuestionTotalPages(data.total_pages ?? Math.max(1, Math.ceil((data.total ?? 0) / questionPageSize)));
        setQuestionHasNext(Boolean(data.has_next ?? (list.length >= questionPageSize)));
        if (list.length && !selectedQuestion) {
          fetchQuestionDetail(list[0].id);
        }
      } catch (err) {
        console.error('fetchPyqs error', err);
      } finally {
        if (!cancelled) setIsLoadingQuestions(false);
      }
    };

    const fetchAnalyticsSummary = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/analytics/summary`);
        const data = await res.json();
        if (!cancelled) setAnalyticsSummary(data);
      } catch (err) {
        console.error('fetchAnalyticsSummary error', err);
      }
    };

    fetchPyqs();
    fetchAnalyticsSummary();

    return () => {
      cancelled = true;
    };
  }, [questionPage, questionPageSize]);

  const fetchQuestionDetail = async (id) => {
    const questionId = typeof id === 'object' && id !== null ? id.id : id;
    if (!questionId) return;
    try {
      const res = await fetch(`${API_BASE}/api/pyqs/${encodeURIComponent(questionId)}`);
      const data = await res.json();
      const q = data.question ?? data;
      const mapped = {
        id: q.question_id,
        title: q.question_text ?? q.title ?? 'Untitled',
        summary: q.question_text ?? q.summary ?? '',
        year: q.year,
        topic: q.topic,
        difficulty: q.difficulty,
        importance: q.importance_score ?? q.importance ?? 0,
        accuracy: q.confidence ?? 0,
        tags: q.semantic_tags_json ?? [],
        analytics: {
          conceptDepth: (data.analytics && data.analytics.conceptual_depth) ?? data.conceptual_depth ?? 0,
          similarQuestions: (data.analytics && data.analytics.similar_questions) ?? 0,
        },
        download_url: data.download_url,
      };
      setSelectedQuestion(mapped);
    } catch (err) {
      console.error('fetchQuestionDetail error', err);
    }
  };

  const activeLabel = useMemo(() => {
    if (activeTab === 'dashboard') return 'Archive overview';
    if (activeTab === 'analytics') return 'Signal board';
    if (activeTab === 'ingestion') return 'Ingestion desk';
    return 'Research agent';
  }, [activeTab]);

  return (
    <div className="relative min-h-screen text-[#f5efe6]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.04),transparent_28%),radial-gradient(circle_at_top_right,rgba(245,158,11,0.08),transparent_22%),linear-gradient(180deg,rgba(255,255,255,0.02),transparent_26%)]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:64px_100%,100%_64px] opacity-15" />

      <div className="relative mx-auto w-[min(1320px,calc(100vw-1.25rem))] px-0 py-5 sm:w-[min(1320px,calc(100vw-2rem))] sm:py-7">
        <header className="flex flex-col items-start justify-between gap-5 pb-5 lg:flex-row lg:items-end">
          <div className="max-w-4xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-amber-400/15 bg-amber-400/8 px-4 py-2 text-[0.68rem] uppercase tracking-[0.28em] text-amber-100/70">
              Midnight observatory archive
              <span className="h-2 w-2 rounded-full bg-amber-300/80 shadow-[0_0_0_6px_rgba(245,158,11,0.08)]" />
            </div>
            <h1 className="max-w-4xl text-4xl font-semibold tracking-[-0.05em] text-[#f7efe1] sm:text-5xl lg:text-6xl">
              PYQ dashboard
            </h1>
            <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300/80 sm:text-base">
              Browse questions, inspect importance signals, and open the agent like a research instrument instead of a flashy AI interface.
            </p>
          </div>

          <div className="inline-flex items-center gap-3 rounded-full border border-white/10 bg-white/5 px-4 py-3 text-[0.72rem] uppercase tracking-[0.18em] text-slate-300 shadow-[0_10px_20px_rgba(0,0,0,0.16)]">
            <span className="h-2.5 w-2.5 rounded-full bg-amber-300 shadow-[0_0_0_6px_rgba(245,158,11,0.08)]" />
            Live Coral data ready
          </div>
        </header>

        <main className={`${shellCard} p-5 sm:p-6`}>
          <div className="mb-5 flex flex-wrap items-center gap-3 rounded-[22px] border border-white/10 bg-[#20242b]/85 p-2">
            <TabButton active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')}>
              Dashboard
            </TabButton>
            <TabButton active={activeTab === 'analytics'} onClick={() => setActiveTab('analytics')}>
              Analytics
            </TabButton>
            <TabButton active={activeTab === 'ingestion'} onClick={() => setActiveTab('ingestion')}>
              Ingestion
            </TabButton>
            <TabButton active={activeTab === 'agent'} onClick={() => setActiveTab('agent')}>
              Agent
            </TabButton>
          </div>

          <div className="mb-5 text-[0.72rem] uppercase tracking-[0.3em] text-amber-100/60">{activeLabel}</div>

          {activeTab === 'dashboard' && (
            <div>
              <DashboardTab pyqs={pyqs} selectedQuestion={selectedQuestion} onSelectQuestion={fetchQuestionDetail} />
              <PaginationControls
                page={questionPage}
                totalPages={effectiveTotalPages}
                totalItems={questionTotalItems}
                canNext={effectiveHasNext && !isLoadingQuestions}
                onPrevious={() => setQuestionPage((current) => Math.max(1, current - 1))}
                onNext={() => setQuestionPage((current) => current + 1)}
              />
              {isLoadingQuestions && (
                <div className="mt-3 text-[0.72rem] uppercase tracking-[0.24em] text-amber-100/60">Loading questions…</div>
              )}
            </div>
          )}
          {activeTab === 'analytics' && <AnalyticsTab summary={analyticsSummary} />}
          {activeTab === 'ingestion' && <IngestionTab />}
          {activeTab === 'agent' && <AgentTab selectedQuestion={selectedQuestion} />}
        </main>
      </div>
    </div>
  );
}
