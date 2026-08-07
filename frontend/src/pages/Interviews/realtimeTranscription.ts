import request from '../../utils/request';

export type RealtimeStatus = 'connecting' | 'connected' | 'reconnecting' | 'unavailable' | 'stopped';

export type RealtimeSegment = {
  id: string;
  speaker?: string;
  text: string;
  start?: number;
  end?: number;
};

type RealtimeSession = {
  token: string;
  expires_at: string;
  ws_path: string;
};

type RealtimeCallbacks = {
  onStatus: (status: RealtimeStatus) => void;
  onPartial: (text: string) => void;
  onSegment: (segment: RealtimeSegment) => void;
};

const TARGET_RATE = 16_000;
const PACKET_MILLISECONDS = 100;
const MAX_BUFFERED_PACKETS = 10_000 / PACKET_MILLISECONDS;
const MAX_SOCKET_BUFFER_BYTES = 512 * 1024;
const STABLE_CONNECTION_MILLISECONDS = 30_000;
const MAX_RECONNECT_DELAY_MILLISECONDS = 15_000;

export const realtimeReconnectDelay = (attempt: number) => (
  Math.min(1000 * (2 ** Math.max(attempt, 0)), MAX_RECONNECT_DELAY_MILLISECONDS)
);

const workletSource = `
class InterviewCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.offset = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    let sourceOffset = 0;
    while (sourceOffset < channel.length) {
      const count = Math.min(channel.length - sourceOffset, this.buffer.length - this.offset);
      this.buffer.set(channel.subarray(sourceOffset, sourceOffset + count), this.offset);
      this.offset += count;
      sourceOffset += count;
      if (this.offset === this.buffer.length) {
        const completed = this.buffer;
        this.port.postMessage(completed, [completed.buffer]);
        this.buffer = new Float32Array(2048);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor('interview-capture-processor', InterviewCaptureProcessor);
`;

const websocketUrl = (path: string, token: string) => {
  const url = new URL(path, window.location.href);
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('token', token);
  return url.toString();
};

const makeId = () => (
  typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `rt-${Date.now()}-${Math.random().toString(16).slice(2)}`
);

export const buildRealtimeSessionStart = (interviewId: string) => ({
  type: 'session.start',
  session_id: makeId(),
  interview_id: interviewId,
  track_id: 'mixed_mic',
  role: 'mixed',
  source: 'mic',
  transcribe: true,
  audio: { encoding: 'pcm_s16le', sample_rate: TARGET_RATE, channels: 1 },
  options: { partial: true, diarization: true },
});

export class RealtimeTranscriptionClient {
  private readonly interviewId: string;
  private readonly recordingSessionId: string;
  private readonly stream: MediaStream;
  private readonly callbacks: RealtimeCallbacks;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private socket: WebSocket | null = null;
  private protocolSessionId = '';
  private socketReady = false;
  private stopped = false;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private renewalTimer: ReturnType<typeof setTimeout> | null = null;
  private stableConnectionTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingInput = new Float32Array(0);
  private readonly packets: ArrayBuffer[] = [];

  constructor(
    interviewId: string,
    recordingSessionId: string,
    stream: MediaStream,
    callbacks: RealtimeCallbacks,
  ) {
    this.interviewId = interviewId;
    this.recordingSessionId = recordingSessionId;
    this.stream = stream;
    this.callbacks = callbacks;
  }

  async start() {
    if (!window.AudioWorkletNode || !window.AudioContext) {
      this.callbacks.onStatus('unavailable');
      return;
    }
    try {
      await this.startCapture();
      void this.connect(false);
    } catch {
      this.callbacks.onStatus('unavailable');
    }
  }

  private async startCapture() {
    this.context = new AudioContext();
    await this.context.resume();
    const moduleUrl = URL.createObjectURL(new Blob([workletSource], { type: 'text/javascript' }));
    try {
      await this.context.audioWorklet.addModule(moduleUrl);
    } finally {
      URL.revokeObjectURL(moduleUrl);
    }
    this.source = this.context.createMediaStreamSource(this.stream);
    this.worklet = new AudioWorkletNode(this.context, 'interview-capture-processor');
    const silentOutput = this.context.createGain();
    silentOutput.gain.value = 0;
    this.worklet.port.onmessage = (event: MessageEvent<Float32Array>) => this.acceptInput(event.data);
    this.source.connect(this.worklet);
    this.worklet.connect(silentOutput).connect(this.context.destination);
  }

  private acceptInput(input: Float32Array) {
    if (this.stopped || !this.context) return;
    const merged = new Float32Array(this.pendingInput.length + input.length);
    merged.set(this.pendingInput);
    merged.set(input, this.pendingInput.length);
    this.pendingInput = merged;

    const sourceFrames = Math.round(this.context.sampleRate * PACKET_MILLISECONDS / 1000);
    while (this.pendingInput.length >= sourceFrames) {
      const packetInput = this.pendingInput.slice(0, sourceFrames);
      this.pendingInput = this.pendingInput.slice(sourceFrames);
      this.sendOrBuffer(this.toPcm16(packetInput));
    }
  }

  private toPcm16(input: Float32Array): ArrayBuffer {
    const outputFrames = TARGET_RATE * PACKET_MILLISECONDS / 1000;
    const output = new Int16Array(outputFrames);
    const scale = (input.length - 1) / Math.max(outputFrames - 1, 1);
    for (let index = 0; index < outputFrames; index += 1) {
      const position = index * scale;
      const left = Math.floor(position);
      const right = Math.min(left + 1, input.length - 1);
      const sample = input[left] + (input[right] - input[left]) * (position - left);
      output[index] = Math.round(Math.max(-1, Math.min(1, sample)) * (sample < 0 ? 32768 : 32767));
    }
    return output.buffer;
  }

  private sendOrBuffer(packet: ArrayBuffer) {
    if (
      this.socketReady
      && this.socket?.readyState === WebSocket.OPEN
      && this.socket.bufferedAmount < MAX_SOCKET_BUFFER_BYTES
    ) {
      this.flushPackets();
      this.socket.send(packet);
      return;
    }
    this.packets.push(packet);
    if (this.packets.length > MAX_BUFFERED_PACKETS) this.packets.shift();
  }

  private flushPackets() {
    while (
      this.packets.length
      && this.socketReady
      && this.socket?.readyState === WebSocket.OPEN
      && this.socket.bufferedAmount < MAX_SOCKET_BUFFER_BYTES
    ) {
      this.socket.send(this.packets.shift()!);
    }
  }

  private async connect(isReconnect: boolean) {
    if (this.stopped) return;
    this.callbacks.onStatus(isReconnect ? 'reconnecting' : 'connecting');
    try {
      const session = await request.post(
        `/interviews/${this.interviewId}/recording/realtime-session`,
        { session_id: this.recordingSessionId },
      ) as RealtimeSession;
      if (this.stopped) return;
      const socket = new WebSocket(websocketUrl(session.ws_path, session.token));
      socket.binaryType = 'arraybuffer';
      this.socket = socket;
      this.socketReady = false;
      socket.onopen = () => {
        if (this.socket !== socket || this.stopped) return;
        const startPayload = buildRealtimeSessionStart(this.interviewId);
        this.protocolSessionId = startPayload.session_id;
        socket.send(JSON.stringify(startPayload));
      };
      socket.onmessage = (event) => this.handleMessage(socket, event.data);
      socket.onerror = () => socket.close();
      socket.onclose = (event) => {
        if (this.socket !== socket || this.stopped) return;
        if (event.code !== 1000) {
          console.warn('Realtime transcription socket closed', {
            code: event.code,
            reason: event.reason || 'no reason supplied',
          });
        }
        if (this.stableConnectionTimer) {
          clearTimeout(this.stableConnectionTimer);
          this.stableConnectionTimer = null;
        }
        this.socket = null;
        this.socketReady = false;
        this.scheduleReconnect();
      };
      this.scheduleRenewal(session.expires_at);
    } catch {
      this.scheduleReconnect();
    }
  }

  private handleMessage(socket: WebSocket, raw: unknown) {
    if (this.socket !== socket || typeof raw !== 'string') return;
    try {
      const event = JSON.parse(raw) as Record<string, unknown>;
      if (event.type === 'session.ready') {
        this.socketReady = true;
        this.callbacks.onStatus('connected');
        this.flushPackets();
        if (this.stableConnectionTimer) clearTimeout(this.stableConnectionTimer);
        this.stableConnectionTimer = setTimeout(() => {
          if (this.socket === socket && this.socketReady && !this.stopped) {
            this.reconnectAttempt = 0;
          }
          this.stableConnectionTimer = null;
        }, STABLE_CONNECTION_MILLISECONDS);
      } else if (event.type === 'transcript.partial') {
        this.callbacks.onPartial(typeof event.text === 'string' ? event.text : '');
      } else if (event.type === 'segment.final') {
        const text = typeof event.text === 'string' ? event.text.trim() : '';
        if (!text) return;
        this.callbacks.onPartial('');
        this.callbacks.onSegment({
          id: `${this.protocolSessionId}:${String(event.segment_id || makeId())}`,
          speaker: typeof event.speaker === 'string'
            ? event.speaker
            : (typeof event.speaker === 'number' ? `speaker_${event.speaker}` : undefined),
          text,
          start: typeof event.start === 'number' ? event.start : undefined,
          end: typeof event.end === 'number' ? event.end : undefined,
        });
      } else if (event.type === 'error') {
        socket.close();
      }
    } catch {
      // Ignore non-protocol messages; recording remains authoritative.
    }
  }

  private scheduleReconnect() {
    if (this.stopped || this.reconnectTimer) return;
    this.callbacks.onStatus(this.reconnectAttempt ? 'reconnecting' : 'unavailable');
    const delay = realtimeReconnectDelay(this.reconnectAttempt);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect(true);
    }, delay);
  }

  private scheduleRenewal(expiresAt: string) {
    if (this.renewalTimer) clearTimeout(this.renewalTimer);
    const renewIn = Math.max(new Date(expiresAt).getTime() - Date.now() - 120_000, 60_000);
    this.renewalTimer = setTimeout(() => {
      const previous = this.socket;
      this.socket = null;
      this.socketReady = false;
      previous?.close();
      void this.connect(true);
    }, renewIn);
  }

  stop() {
    if (this.stopped) return;
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.renewalTimer) clearTimeout(this.renewalTimer);
    if (this.stableConnectionTimer) clearTimeout(this.stableConnectionTimer);
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'session.stop' }));
    }
    this.socket?.close();
    this.socket = null;
    this.worklet?.disconnect();
    this.source?.disconnect();
    void this.context?.close();
    this.callbacks.onStatus('stopped');
  }
}
