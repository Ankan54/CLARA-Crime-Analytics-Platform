import { useEffect, useMemo, useState } from "react";
import {
  LANDING_HERO_SLIDES,
  nodeFillColor,
  nodeStrokeColor,
  nodeStrokeWidth,
  type LandingHeroSlide,
} from "../../data/scenarioHeroGraphs";

export function ScenarioHeroGraph({
  slide,
  className = "hero-slide-svg",
}: {
  slide: LandingHeroSlide;
  className?: string;
}) {
  const nodeLookup = useMemo(
    () => new Map(slide.nodes.map((node) => [node.id, node])),
    [slide],
  );

  return (
    <svg
      key={slide.id}
      className={className}
      viewBox="0 0 480 380"
      role="img"
      aria-label={slide.ariaLabel}
    >
      {slide.edges.map((edge, index) => {
        const from = nodeLookup.get(edge.from);
        const to = nodeLookup.get(edge.to);
        if (!from || !to) {
          return null;
        }
        return (
          <line
            key={`${slide.id}-edge-${edge.from}-${edge.to}-${index}`}
            className={`edge ${edge.tone}`}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
          />
        );
      })}

      {slide.nodes.map((node) => (
        <g key={`${slide.id}-node-${node.id}`}>
          {node.halo && <circle className="leader-halo" cx={node.x} cy={node.y} r={node.r} />}
          <circle
            className={`dot${node.pulseClass ? ` ${node.pulseClass}` : ""}`}
            cx={node.x}
            cy={node.y}
            r={node.r}
            fill={nodeFillColor(node)}
            stroke={nodeStrokeColor(node.tone)}
            strokeWidth={nodeStrokeWidth(node.tone)}
          />
        </g>
      ))}

      {slide.texts.map((text, index) => (
        <text
          key={`${slide.id}-text-${index}`}
          className={text.className}
          x={text.x}
          y={text.y}
          textAnchor={text.anchor ?? "middle"}
        >
          {text.value}
        </text>
      ))}
    </svg>
  );
}

export function LandingScenarioSlideshow() {
  const [activeSlideIndex, setActiveSlideIndex] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const timer = window.setInterval(() => {
      setActiveSlideIndex((currentIndex) => (currentIndex + 1) % LANDING_HERO_SLIDES.length);
    }, 15000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  const activeSlide = LANDING_HERO_SLIDES[activeSlideIndex];

  return (
    <div className="hero-visual">
      <div className="hero-slide-head">
        <span className="hero-slide-kicker">
          Scenario {String(activeSlideIndex + 1).padStart(2, "0")} /{" "}
          {String(LANDING_HERO_SLIDES.length).padStart(2, "0")}
        </span>
        <strong>{activeSlide.title}</strong>
      </div>

      <ScenarioHeroGraph slide={activeSlide} />

      <p className="hero-caption">
        <span className="hero-caption-tag">Scenario</span>
        {activeSlide.caption}
      </p>

      <div className="hero-slide-dots" aria-label="Landing scenario slideshow">
        {LANDING_HERO_SLIDES.map((slide, index) => (
          <button
            key={slide.id}
            className={`hero-slide-dot${index === activeSlideIndex ? " active" : ""}`}
            type="button"
            onClick={() => setActiveSlideIndex(index)}
            aria-label={`Show ${slide.title}`}
            aria-pressed={index === activeSlideIndex}
          />
        ))}
      </div>
    </div>
  );
}
