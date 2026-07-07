import { describe, expect, it } from 'vitest';
import { extractCloudRagFileCards, parseSSEBlock } from './sse';

function makeAgentFileUrl(filename: string) {
  const bytes = new TextEncoder().encode(JSON.stringify({ path: `/workspace/knowledge/${filename}` }));
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const payload = btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  return `http://localhost:8090/files/${payload}.${'a'.repeat(64)}`;
}

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

describe('CloudRAG agent file links', () => {
  it('extracts signed agent file links into cards without exposing the raw link text', () => {
    const url = makeAgentFileUrl('项目文档.md');
    const token = url.split('/files/')[1];
    const parsed = extractCloudRagFileCards(`文件下载地址：\n${url}`);

    expect(parsed.content).toBe('文件下载地址：');
    expect(parsed.fileCards).toEqual([
      {
        id: url,
        name: '项目文档.md',
        sourceUrl: url,
        url: `/files/${token}`,
      },
    ]);
  });

  it('keeps ordinary assistant text exactly unchanged', () => {
    const content =
      '根据您的搜索，关键词“项目文档”找到了以下 2 个匹配文件：\n\n' +
      '1. **模块一-项目总览与部署架构.md**\n\n' +
      '路径：`C:\\Users\\安\\Desktop\\云计算与大数据\\期末任务\\knowledge\\模块一-项目总览与部署架构.md`\n\n' +
      '请问您想打开哪一个文件？请输入序号（1 或 2）。';

    const parsed = extractCloudRagFileCards(content);

    expect(parsed.content).toBe(content);
    expect(parsed.fileCards).toEqual([]);
  });

  it('does not treat ordinary urls or incomplete streaming tokens as file cards', () => {
    const ordinaryUrl = 'http://localhost:8090/health';
    const partialFileUrl = 'http://localhost:8090/files/eyJwYXRoIjoiL3dvcmtzcGFjZS9rbm93bGVkZ2Uv';

    expect(extractCloudRagFileCards(ordinaryUrl)).toEqual({ content: ordinaryUrl, fileCards: [] });
    expect(extractCloudRagFileCards(partialFileUrl)).toEqual({ content: partialFileUrl, fileCards: [] });
  });
});
