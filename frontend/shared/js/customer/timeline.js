import { statusLabel } from './status.js';

export function createTimeline(steps = []) {
  const list = document.createElement('ol');
  list.className = 'customer-timeline';
  for (const step of steps) {
    const item = document.createElement('li');
    item.className = `timeline-item timeline-${step.state || 'upcoming'}`;
    const marker = document.createElement('span');
    marker.className = 'timeline-marker';
    marker.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('div');
    copy.className = 'timeline-copy';
    const title = document.createElement('strong');
    title.textContent = step.label || statusLabel(step.status);
    copy.append(title);
    if (step.at) {
      const time = document.createElement('time');
      time.dateTime = step.at;
      time.textContent = new Date(step.at).toLocaleString();
      copy.append(time);
    }
    item.append(marker, copy);
    list.append(item);
  }
  return list;
}

export function renderPublicTimeline(steps = [], list) {
  const states = {
    done: 'Completed',
    now: 'Current step',
    failed: 'Problem',
    next: 'Upcoming',
  };
  const check = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M3 7.5l2.5 2.5L11 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const cross = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M4 4l6 6M10 4l-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
  list.replaceChildren();

  for (const step of steps) {
    const state = states[step.state] ? step.state : 'next';
    const item = document.createElement('li');
    item.className = state;
    const marker = document.createElement('span');
    marker.className = 'mark';
    if (state === 'done') marker.innerHTML = check;
    else if (state === 'failed') marker.innerHTML = cross;
    else {
      const dot = document.createElement('span');
      dot.className = 'mark-dot';
      marker.append(dot);
    }
    const label = document.createElement('span');
    label.className = 'step-label';
    label.textContent = step.label;
    const screenReaderState = document.createElement('span');
    screenReaderState.className = 'sr';
    screenReaderState.textContent = states[state];
    item.append(marker, label, screenReaderState);
    if (step.time) {
      const time = document.createElement('span');
      time.className = 'step-time';
      time.textContent = step.time;
      item.append(time);
    }
    if (step.note) {
      const note = document.createElement('span');
      note.className = 'step-note';
      note.textContent = step.note;
      item.append(note);
    }
    list.append(item);
  }
}
