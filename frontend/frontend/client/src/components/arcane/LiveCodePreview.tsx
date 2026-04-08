// Stub component - LiveCodePreview placeholder
import React from 'react';

export interface StepPayload {
  id: string;
  type: string;
  content?: string;
  status?: string;
}

interface LiveCodePreviewProps {
  steps?: StepPayload[];
  isGenerating?: boolean;
  expanded?: boolean;
}

const LiveCodePreview: React.FC<LiveCodePreviewProps> = ({ steps = [], isGenerating = false, expanded = false }) => {
  return (
    <div className="p-4 bg-gray-50 rounded-lg">
      {isGenerating ? (
        <div className="text-sm text-gray-500 animate-pulse">Выполняется...</div>
      ) : steps.length === 0 ? (
        <div className="text-sm text-gray-400">Нет шагов</div>
      ) : (
        <div className="space-y-2">
          {steps.map(s => (
            <div key={s.id} className="text-xs font-mono text-gray-600 bg-white p-2 rounded border">{s.content || s.type}</div>
          ))}
        </div>
      )}
    </div>
  );
};

export default LiveCodePreview;
