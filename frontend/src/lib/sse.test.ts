import { describe, expect, it } from 'vitest';
import { parseSSEBlock } from './sse';

describe('SSE parser', () => {
  it('parses named SSE event blocks', () => {
    const parsed = parseSSEBlock('event: message\ndata: {"token":"你好","index":0}');

    expect(parsed).toEqual({
      event: 'message',
      data: { token: '你好', index: 0 },
    });
  });

  it('keeps event and data together when chunks are reassembled by blank lines', () => {
    let buffer = '';
    const chunks = [
      'event: message\n',
      'data: {"token":"你","index":0}\n\n',
      'event: done\n',
      'data: {"conversation_id":"c1"}\n\n',
    ];
    const events = [];

    for (const chunk of chunks) {
      buffer += chunk;
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || '';
      for (const block of blocks) {
        const parsed = parseSSEBlock(block);
        if (parsed) events.push(parsed);
      }
    }

    expect(events).toEqual([
      { event: 'message', data: { token: '你', index: 0 } },
      { event: 'done', data: { conversation_id: 'c1' } },
    ]);
  });
});
