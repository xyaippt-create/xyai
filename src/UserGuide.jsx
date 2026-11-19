import React, { createContext, useContext, useLayoutEffect, useRef, useState } from "react";
import HddeIcon from "./HddeIcon.jsx";
import { articles, guideSections } from "./userGuideArticles.js";
import "./userGuide.css";

const OpenGuide = createContext(null);

function normalizeText(text) {
  return text.normalize("NFKC").toLowerCase().trim();
}

const searchIndex = guideSections.flatMap((section) => section.topics.map((id) => {
  const article = articles[id];
  const body = [section.title, section.searchAlias, article.title, article.intro, article.result,
    ...article.steps.map((step) => `${step.title} ${step.text}`)].join("\n");
  return { id, section: section.title, title: normalizeText(article.title), body: normalizeText(body) };
}));

function searchGuide(query) {
  const terms = query.split(/\s+/);
  return searchIndex.filter(({ body }) => terms.every((term) => body.includes(term)))
    .map((entry) => ({ ...entry, titleHits: terms.filter((term) => entry.title.includes(term)).length }))
    .sort((a, b) => b.titleHits - a.titleHits);
}

export function UserGuideTrigger({ workspace = false }) {
  const open = useContext(OpenGuide);
  return (
    <button type="button" className={`hdde-guide-trigger ${workspace ? "hdde-retouch-import" : "hdde-topbar-feedback"}`}
      aria-label="使用指南" aria-haspopup="dialog" title="使用指南" onClick={() => open(null)}>
      <HddeIcon name="book" /><span>使用指南</span>
    </button>
  );
}

export function SaveGuideLink() {
  const open = useContext(OpenGuide);
  return <a href="#guide-save" aria-haspopup="dialog" onClick={(event) => {
    event.preventDefault();
    open("save", "guide-save-choice");
  }}>如何保存？</a>;
}

export function UserGuideProvider({ children }) {
  const panel = useRef(null);
  const viewer = useRef(null);
  const heading = useRef(null);
  const lastTopic = useRef(null);
  const searchInput = useRef(null);
  const [query, setQuery] = useState("");
  const searchTerm = normalizeText(query);
  const [selection, setSelection] = useState({ topic: null });
  const { topic, anchor } = selection;
  const [picture, setPicture] = useState(null);
  const [actualSize, setActualSize] = useState(false);
  const article = articles[topic];
  const matches = !article && searchTerm ? searchGuide(searchTerm) : null;

  function openGuide(id, anchor) {
    lastTopic.current = id;
    setQuery("");
    setSelection({ topic: id, anchor });
    panel.current.showModal();
  }

  function selectTopic(id) {
    if (!topic) lastTopic.current = id;
    setSelection({ topic: id });
  }

  useLayoutEffect(() => {
    if (!panel.current.open) return;
    const step = anchor && document.getElementById(anchor);
    if (step) {
      step.focus({ preventScroll: true });
      step.scrollIntoView({ block: "start" });
      return;
    }
    panel.current.scrollTop = 0;
    if (topic) heading.current?.focus({ preventScroll: true });
    else if (lastTopic.current) panel.current.querySelector(`[data-topic="${lastTopic.current}"]`)?.focus();
  }, [selection]);

  return (
    <OpenGuide.Provider value={openGuide}>
      {children}
      <dialog ref={panel} className="hdde-guide-panel" aria-labelledby="guide-title" closedby="any">
        <header>
          <h2 id="guide-title">使用指南</h2>
          <button type="button" aria-label="关闭使用指南" onClick={() => panel.current.close()}><HddeIcon name="close" /></button>
        </header>
        {article ? <article>
          <button type="button" className="hdde-guide-back" onClick={() => setSelection({ topic: null })}><HddeIcon name="back" size={14} />{searchTerm ? "返回搜索结果" : "目录"}</button>
          <h3 id={`guide-${topic}`} tabIndex="-1" ref={heading}>{article.title}</h3>
          <p className="hdde-guide-intro">{article.intro}</p>
          <ol>{article.steps.map((step) => <li key={step.title}>
            <strong id={step.anchor} tabIndex={step.anchor ? -1 : undefined}>{step.title}</strong>
            <p>{step.text}</p>
            {step.picture && <figure>
              <button type="button" title="点击放大" aria-label={`放大配图：${step.picture.alt}`} onClick={() => {
                setPicture(step.picture);
                setActualSize(false);
                viewer.current.showModal();
              }}><img src={step.picture.src} alt={step.picture.alt} width="1440" height="900" /><HddeIcon name="plus" size={18} /></button>
            </figure>}
          </li>)}</ol>
          <p className="hdde-guide-result">{article.result}</p>
          {article.next && <button type="button" className="hdde-guide-next" onClick={() => selectTopic(article.next)}>
            接着看《{articles[article.next].title}》<HddeIcon name="chevron" size={16} />
          </button>}
        </article> : <>
          <div className="hdde-guide-search" role="search" aria-label="使用指南">
            <label htmlFor="guide-search">搜索教程</label>
            <div className="hdde-guide-search-field">
              <HddeIcon name="search" size={18} />
              <input id="guide-search" ref={searchInput} role="searchbox" autoComplete="off"
                placeholder="输入功能、问题或按钮名称" value={query} onChange={(event) => setQuery(event.target.value)} />
              {query && <button type="button" aria-label="清空搜索" onClick={() => {
                setQuery("");
                searchInput.current.focus();
              }}><HddeIcon name="close" size={16} /></button>}
            </div>
            <p role="status">{matches && (matches.length ? `找到 ${matches.length} 篇教程` : "没有找到相关教程，试试更短的关键词。")}</p>
          </div>
          <nav aria-label={matches ? "教程搜索结果" : "指南目录"}>
          {matches ? matches.map(({ id, section }) => <button key={id} type="button" data-topic={id} onClick={() => selectTopic(id)}>
            <span>{articles[id].title}<small className="hdde-guide-result-section">{section}</small></span><HddeIcon name="chevron" size={16} />
          </button>) : guideSections.map((section) => <section key={section.title}>
            <h3>{section.title}</h3>
            {section.topics.map((id) => <button key={id} type="button" data-topic={id} onClick={() => selectTopic(id)}>
              {articles[id].title}<HddeIcon name="chevron" size={16} />
            </button>)}
          </section>)}
          </nav>
        </>}
      </dialog>
      <dialog ref={viewer} className="hdde-guide-viewer" aria-label="放大配图" onClose={() => setPicture(null)}>
        <header><strong>放大配图</strong>
          <button type="button" className="hdde-guide-zoom" onClick={() => setActualSize(!actualSize)}>
            {actualSize ? "适合窗口" : "原始大小"}
          </button>
          <button type="button" aria-label="关闭放大配图" onClick={() => viewer.current.close()}><HddeIcon name="close" /></button>
        </header>
        {picture && <div data-actual-size={actualSize}><img src={picture.src} alt={picture.alt} /></div>}
      </dialog>
    </OpenGuide.Provider>
  );
}
