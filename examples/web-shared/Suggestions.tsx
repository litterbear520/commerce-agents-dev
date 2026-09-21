"use client";

export function Suggestions({
  suggestions,
  onPick,
  disabled,
}: {
  suggestions: string[];
  onPick: (text: string) => void;
  disabled?: boolean;
}) {
  if (!suggestions.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {suggestions.map((suggestion, index) => (
        <button
          key={suggestion}
          type="button"
          disabled={disabled}
          onClick={() => onPick(suggestion)}
          className="chip"
          style={{ animationDelay: `${index * 70}ms` }}
        >
          {suggestion}
        </button>
      ))}
    </div>
  );
}
