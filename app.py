#!/usr/bin/env python3
"""FALSE GREEN: a local, controlled asynchronous booking simulation."""

import argparse
from contextlib import contextmanager
import datetime as dt
import hmac
import ipaddress
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import uuid


class BookingService:
    """One real worker; job state is transient, confirmed records are durable."""

    def __init__(self, database, worker_delay=0.8):
        self.database = str(database)
        self.worker_delay = worker_delay
        self.lock = threading.RLock()
        self.jobs = {}
        self.last_job_id = None
        self.fail_next = False
        self.generation = 0
        self.closed = False
        self.queue = queue.Queue()
        self.stop = threading.Event()
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY, customer TEXT NOT NULL,
                date TEXT NOT NULL, time TEXT NOT NULL,
                party_size INTEGER NOT NULL, status TEXT NOT NULL
                CHECK (status = 'confirmed'), created_at TEXT NOT NULL)""")
        self.worker = threading.Thread(target=self._work, name="booking-worker", daemon=True)
        self.worker.start()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def validate(data):
        if not isinstance(data, dict):
            raise ValueError("Please send a booking object.")
        customer = data.get("customer")
        if not isinstance(customer, str) or not 1 <= len(customer.strip()) <= 100:
            raise ValueError("Customer name must contain 1–100 characters.")
        if any(ord(c) < 32 for c in customer):
            raise ValueError("Customer name cannot contain control characters.")
        try:
            customer.encode("utf-8")
        except UnicodeError:
            raise ValueError("Customer name must contain valid Unicode text.") from None
        date, booking_time = data.get("date"), data.get("time")
        try:
            if not isinstance(date, str) or dt.date.fromisoformat(date).isoformat() != date:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Choose a valid date (YYYY-MM-DD).") from None
        try:
            if (not isinstance(booking_time, str) or len(booking_time) != 5
                    or dt.time.fromisoformat(booking_time).strftime("%H:%M") != booking_time):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Choose a valid time (HH:MM).") from None
        party = data.get("party_size")
        if type(party) is not int or not 1 <= party <= 12:
            raise ValueError("Party size must be a whole number from 1 to 12.")
        return {"customer": customer.strip(), "date": date, "time": booking_time,
                "party_size": party}

    def accept(self, data):
        booking = self.validate(data)
        with self.lock:
            if self.closed:
                raise RuntimeError("The booking worker is shutting down.")
            job_id = uuid.uuid4().hex
            job = dict(booking, id=job_id, status="pending",
                       created_at=dt.datetime.now(dt.timezone.utc).isoformat())
            # Reserve the fault for exactly the next valid accepted job.
            should_fail, self.fail_next = self.fail_next, False
            self.jobs[job_id] = job
            self.last_job_id = job_id
            self.queue.put((self.generation, job_id, should_fail))
            return dict(job)

    def arm_failure(self):
        with self.lock:
            self.fail_next = True

    def reset(self):
        with self.lock:
            with self.connect() as db:
                db.execute("DELETE FROM bookings")
            # Invalidates even a job already sleeping in the worker.
            self.generation += 1
            self.jobs.clear()
            self.last_job_id = None
            self.fail_next = False

    def status(self, job_id):
        with self.lock:
            with self.connect() as db:
                row = db.execute("SELECT * FROM bookings WHERE id = ?", (job_id,)).fetchone()
            if row is not None:
                return dict(row)
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def last_outcome(self):
        # Private read-only observation; failed jobs never create SQLite rows.
        with self.lock:
            job = self.status(self.last_job_id) if self.last_job_id else None
            if not job:
                return {"customer": None, "status": "none", "accepted": False}
            return {"customer": job["customer"], "status": job["status"],
                    "accepted": True, "id": job["id"]}

    def bookings(self):
        with self.lock, self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM bookings ORDER BY created_at DESC, id DESC")]

    def _work(self):
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                generation, job_id, should_fail = item
                if self.stop.wait(self.worker_delay):
                    continue
                with self.lock:
                    if generation != self.generation:
                        continue
                    job = self.jobs[job_id]
                    if should_fail:
                        job.update(status="failed", error="The worker could not save this booking. Please try again.")
                        continue
                    try:
                        with self.connect() as db:
                            db.execute("""INSERT INTO bookings
                                (id, customer, date, time, party_size, status, created_at)
                                VALUES (?, ?, ?, ?, ?, 'confirmed', ?)""",
                                (job_id, job["customer"], job["date"], job["time"],
                                 job["party_size"], job["created_at"]))
                        # A confirmed job is observable only AFTER the commit succeeds.
                        job["status"] = "confirmed"
                    except sqlite3.Error:
                        job.update(status="failed", error="The worker could not save this booking. Please try again.")
            finally:
                self.queue.task_done()

    def close(self):
        with self.lock:
            self.closed = True
        self.stop.set()
        self.queue.put(None)
        self.worker.join(timeout=5)


HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>False Green — A table for your next moment</title>
  <style>
    :root{--ink:#243c32;--muted:#66736b;--green:#305e47;--paper:#f7f6ef;--line:#dde2d5;--lime:#dfedb9;--red:#973a2b}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    button,input,select{font:inherit}button,a,input,select{-webkit-tap-highlight-color:transparent}button,a{touch-action:manipulation}
    button{cursor:pointer}a{color:inherit}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #a28b33;outline-offset:4px}
    .shell{max-width:1160px;margin:auto;padding:0 36px}header{border-bottom:1px solid var(--line)}.bar{display:flex;align-items:center;justify-content:space-between;min-height:98px;gap:20px}
    .brand{text-decoration:none;display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:-.7px;font-size:21px}.mark{background:var(--ink);color:var(--lime);width:38px;height:38px;display:grid;place-items:center;border-radius:12px;font-size:23px}
    nav{display:flex;gap:26px;align-items:center}nav a{text-decoration:none;font-size:14px;font-weight:600;padding:8px 0;border-bottom:2px solid transparent}nav a[aria-current=page]{border-color:var(--green)}
    .local{font-size:11px;letter-spacing:1.4px;text-transform:uppercase;display:flex;align-items:center;gap:8px}.dot{width:7px;height:7px;background:#62864b;border-radius:50%}
    main{padding-top:54px;padding-bottom:55px}.eyebrow{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;display:flex;align-items:center;gap:10px}.eyebrow:before{content:"";width:25px;height:1px;background:currentColor}
    .hero{display:grid;grid-template-columns:1fr 1fr;gap:75px;align-items:start;margin-top:25px}.intro{padding-top:12px}h1{font:normal clamp(44px,5.5vw,69px)/1.08 Georgia,serif;letter-spacing:-2.5px;margin:14px 0 24px}h1 em{color:#638157;font-weight:normal}p{margin:0 0 18px}.intro>p{max-width:365px;color:var(--muted);font-size:16px}
    .scene{position:relative;overflow:hidden;height:185px;border-radius:90px 90px 12px 12px;margin-top:35px;background:#e7ebd9;display:flex;align-items:center;justify-content:center;border:1px solid #dce2cf}
    .table{position:relative;width:198px;height:106px;border-radius:50%;background:#b5c39d;border:9px solid #d8ddc7;box-shadow:0 17px 0 -9px #9caa86;transform:rotate(-12deg)}
    .plate{position:absolute;top:22px;width:46px;height:46px;border-radius:50%;border:7px solid #f7f6eb;background:#e3e6d8;box-shadow:0 2px 2px #0001}.plate.one{left:14px}.plate.two{right:14px}.vase{position:absolute;width:18px;height:27px;background:#647f58;left:80px;top:30px;border-radius:3px 3px 8px 8px}.vase:before{content:"";position:absolute;width:20px;height:29px;border-radius:20px 0;background:#355b3d;left:-12px;top:-24px;transform:rotate(-25deg)}.vase:after{content:"";position:absolute;width:14px;height:24px;border-radius:0 15px;background:#789653;left:8px;top:-29px;transform:rotate(28deg)}
    .scene-caption{display:flex;justify-content:space-between;margin-top:12px;color:var(--muted);font-size:10px;letter-spacing:1.5px;text-transform:uppercase}
    .card{background:#fffefa;border:1px solid var(--line);border-radius:19px;padding:32px;box-shadow:0 14px 45px #293d2510}.card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}.card h2{font:normal 27px/1.2 Georgia,serif;margin:0 0 5px;letter-spacing:-.6px}.small{font-size:13px;color:var(--muted)}.step{font-size:11px;border:1px solid var(--line);border-radius:20px;padding:5px 10px;white-space:nowrap}
    label{display:block;font-size:12px;font-weight:650;margin:0 0 7px}input,select{width:100%;min-width:0;height:48px;border:1px solid #cdd4c8;border-radius:8px;background:#fffefa;padding:0 12px;color:var(--ink)}input:hover,select:hover{border-color:#7e9373}input:focus,select:focus{border-color:var(--green)}.field{margin-bottom:18px}.row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
    .primary,.secondary{display:inline-flex;justify-content:center;align-items:center;min-height:48px;border-radius:8px;padding:11px 19px;font-weight:650;font-size:14px;text-decoration:none}.primary{background:var(--green);color:white;border:1px solid var(--green);width:100%;gap:14px}.primary:hover{background:#244b37}.primary:disabled{opacity:.65;cursor:wait}.secondary{background:transparent;border:1px solid #b9c7ad;color:var(--green)}.note{font-size:11px;color:var(--muted);text-align:center;margin:12px 0 0}.form-foot{margin-top:23px;padding-top:18px;border-top:1px solid var(--line);display:flex;gap:10px;font-size:12px;color:var(--muted)}
    .promise{display:grid;grid-template-columns:repeat(3,1fr);gap:25px;margin-top:55px;padding-top:25px;border-top:1px solid var(--line)}.promise b{display:block;font-size:12px;margin-bottom:5px}.promise p{font-size:12px;color:var(--muted);margin:0}.num{font:italic 20px Georgia,serif;color:#849774;display:block;margin-bottom:12px}
    footer{border-top:1px solid var(--line);padding:20px 0;color:var(--muted);font-size:11px}.footer-inner{display:flex;justify-content:space-between;gap:20px}.tag{display:inline-block;background:#e9eedf;border-radius:5px;font-size:10px;font-weight:650;padding:3px 7px;margin-right:7px;letter-spacing:.6px}
    [hidden]{display:none!important}.outcome{margin-top:20px;border:1px solid #c3d5b4;border-radius:12px;background:#eef4e6;padding:22px}.outcome h3{font:normal 25px Georgia,serif;margin:8px 0 12px}.outcome p{font-size:13px;overflow-wrap:anywhere}.outcome.error{background:#fff0eb;border-color:#e7c4ba;color:var(--red)}.outcome .secondary{margin-top:4px}.reference{font-family:monospace;font-size:11px!important;color:var(--muted)}
    .list-head{display:flex;justify-content:space-between;align-items:center;gap:20px;margin:22px 0 30px}.list-head h1{font-size:47px;margin:0 0 15px}.list-head p{color:var(--muted);font-size:14px}.list-head button{width:auto;white-space:nowrap}.empty{text-align:center;padding:55px 25px}.empty h2{font:normal 28px Georgia,serif}.empty p{color:var(--muted)}.empty a{margin-top:12px}.booking-item{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:23px 0;border-bottom:1px solid var(--line)}.booking-item:first-child{padding-top:0}.booking-item:last-child{border:0;padding-bottom:0}.booking-item h2{font:normal 24px Georgia,serif;margin:0 0 6px;overflow-wrap:anywhere}.booking-item p{font-size:13px;color:var(--muted);margin:0}.badge{background:#e8f0df;color:#38603d;padding:5px 10px;border-radius:20px;font-size:11px;white-space:nowrap}
    @media(max-width:850px){.hero{gap:32px}h1{font-size:53px}.card{padding:25px}.local{display:none}.shell{padding:0 25px}}
    @media(max-width:620px){.bar{min-height:80px}.brand{font-size:18px}nav{gap:15px}nav a{font-size:12px}.shell{padding:0 20px}main{padding-top:30px}.hero{grid-template-columns:1fr;gap:28px;margin-top:10px}.intro{padding:0}.intro>p{max-width:none}.scene,.scene-caption{display:none}h1{font-size:48px;max-width:350px}.card{padding:23px}.promise{gap:18px;margin-top:32px}.footer-inner{flex-direction:column;gap:8px}.list-head{align-items:start;flex-direction:column}.list-head h1{font-size:40px}.booking-item{align-items:start}.row{gap:12px}}
    @media(prefers-reduced-motion:no-preference){button,a{transition:background .16s,border-color .16s}}
  </style>
</head>
<body>
<header><div class="shell bar"><a class="brand" href="#book" aria-label="False Green home"><span class="mark" aria-hidden="true">✳</span> false green<span style="color:#82936e">.</span></a><nav aria-label="Main navigation"><a href="#book" id="nav-book" aria-current="page">Book a table</a><a href="#bookings" id="nav-bookings">My Bookings</a></nav><span class="local"><span class="dot"></span>Local simulation</span></div></header>
<main class="shell">
  <section id="book-view" aria-labelledby="hero-title">
    <div class="eyebrow">Good company. A little space.</div>
    <div class="hero">
      <div class="intro"><h1 id="hero-title">Make room for<br>the <em>good moments.</em></h1><p>A long lunch. An overdue catch-up. An ordinary evening made a little special. Your next gathering starts here.</p><div class="scene" role="img" aria-label="Illustration of a table set for two, with a small leafy plant"><div class="table"><span class="plate one"></span><span class="plate two"></span><span class="vase"></span></div></div><div class="scene-caption"><span>A seat at the table</span><span>Est. for this demo · 2026</span></div></div>
      <div class="card"><div class="card-top"><div><h2>Your table awaits</h2><span class="small">Just a few details to get started.</span></div><span class="step">01 / Reserve</span></div>
        <form id="booking-form">
          <div class="field"><label for="customer">Customer name</label><input id="customer" name="customer" autocomplete="name" placeholder="e.g. Alex Morgan" maxlength="100" required></div>
          <div class="row"><div class="field"><label for="date">Date</label><input id="date" name="date" type="date" required></div><div class="field"><label for="time">Time</label><input id="time" name="time" type="time" value="19:00" required></div></div>
          <div class="field"><label for="party-size">Party size</label><select id="party-size" name="party_size"><option value="1">1 guest</option><option value="2" selected>2 guests</option><option value="3">3 guests</option><option value="4">4 guests</option><option value="5">5 guests</option><option value="6">6 guests</option><option value="7">7 guests</option><option value="8">8 guests</option><option value="9">9 guests</option><option value="10">10 guests</option><option value="11">11 guests</option><option value="12">12 guests</option></select></div>
          <button id="book-button" class="primary" type="submit">Book <span aria-hidden="true">↗</span></button><p class="note">No payment or account needed.</p>
        </form>
        <div id="result" role="status" aria-live="polite" aria-atomic="true" hidden></div>
        <div class="form-foot"><span aria-hidden="true">ⓘ</span><span>This is a controlled local demo. No real tables are reserved.</span></div>
      </div>
    </div>
    <div class="promise"><div><span class="num">01</span><b>Pick your moment</b><p>Choose a date, time, and your favorite people.</p></div><div><span class="num">02</span><b>Let us take it from here</b><p>Your request is processed by our booking worker.</p></div><div><span class="num">03</span><b>Keep it in view</b><p>Find saved reservations in My Bookings.</p></div></div>
  </section>
  <section id="bookings-view" aria-labelledby="bookings-title" hidden><div class="eyebrow">Your plans, in one place</div><div class="list-head"><div><h1 id="bookings-title">My Bookings</h1><p>Confirmed reservations saved in this local demo.</p></div><button id="refresh-bookings" class="secondary" type="button">Refresh bookings ↻</button></div><div id="bookings-content" class="card" aria-live="polite" aria-busy="false"></div></section>
</main>
<footer><div class="shell footer-inner"><span><span class="tag">SIMULATION</span> A small experiment in booking trust.</span><span>Runs on your machine · No real reservations</span></div></footer>
<script>
  'use strict';
  const $ = id => document.getElementById(id);
  const form = $('booking-form');
  const today = new Date();
  $('date').value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  function element(tag, text, className) {
    const node = document.createElement(tag); node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  async function request(url, options = {}) {
    const response = await fetch(url, {...options, cache:'no-store', signal:AbortSignal.timeout(10000)});
    let data;
    try { data = await response.json(); } catch { throw new Error('The booking service returned an unreadable response.'); }
    if (!response.ok) {
      const error = new Error(data.error || 'The booking service is unavailable.');
      error.status = response.status; throw error;
    }
    return {response, data};
  }
  function showResult(title, message, error=false) {
    const box = $('result'); box.replaceChildren(); box.hidden = false;
    box.className = 'outcome' + (error ? ' error' : '');
    box.append(element('h3', title), element('p', message));
  }
  function bookingLink() {
    const link = element('a','My Bookings','secondary'); link.href='#bookings';
    $('result').append(link);
  }
  let activeJob = null;
  async function pollBooking(job) {
    form.setAttribute('aria-busy','true');
    showResult('Booking pending', 'Your request was accepted. We are waiting for it to be saved.');
    $('result').append(element('p', `Reference · ${job.id}`, 'reference'));
    const deadline = Date.now() + 60000;
    let errors = 0;
    try {
      while (Date.now() < deadline) {
        try {
          const {data} = await request(job.status_url);
          if (data.id !== job.id || !['pending','confirmed','failed'].includes(data.status)) {
            throw new Error('Unexpected booking status.');
          }
          errors = 0;
          if (data.status === 'confirmed') {
            // The status API returns confirmed only after SQLite commits.
            showResult('Booking confirmed', `${data.customer}, your table for ${data.party_size} is booked for ${data.date} at ${data.time}.`);
          } else if (data.status === 'failed') {
            showResult('Booking not confirmed', data.error || 'Your booking could not be saved. Please try again.', true);
          } else {
            await new Promise(resolve => setTimeout(resolve, 350));
            continue;
          }
          $('result').append(element('p', `Reference · ${job.id}`, 'reference'));
          bookingLink();
          activeJob = null; $('book-button').disabled = false;
          if (location.hash === '#bookings') loadBookings();
          return;
        } catch (error) {
          if (++errors >= 3) break;
          await new Promise(resolve => setTimeout(resolve, 750));
        }
      }
      // A timeout or lost status response cannot establish a business outcome.
      showResult('Booking pending', 'We cannot verify the outcome yet. Check this request again or look in My Bookings before booking again.');
      $('result').append(element('p', `Reference · ${job.id}`, 'reference'));
      const retry = element('button','Check booking status','secondary'); retry.type = 'button';
      retry.addEventListener('click', () => pollBooking(job));
      $('result').append(retry); bookingLink();
    } finally {
      form.setAttribute('aria-busy','false');
    }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if ($('book-button').disabled || activeJob) return;
    const booking = {customer:$('customer').value.trim(), date:$('date').value,
      time:$('time').value, party_size:Number($('party-size').value)};
    $('book-button').disabled = true; form.setAttribute('aria-busy','true');
    showResult('Sending your request…', 'Please wait while we contact the booking service.');
    try {
      const {response, data} = await request('/api/bookings', {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify(booking)});
      if (response.status !== 202 || data.status !== 'pending' || typeof data.id !== 'string'
          || !/^[a-f0-9]{32}$/.test(data.id) || data.status_url !== '/api/bookings/' + data.id) {
        throw new Error('Unexpected response from the booking service.');
      }
      activeJob = data;
      await pollBooking(data);
    } catch (error) {
      const rejected = [400,403,415].includes(error.status);
      showResult(rejected ? 'Booking not confirmed' : 'Booking status unavailable',
        error.message + ' Check My Bookings before trying again.', true);
      bookingLink();
    } finally {
      $('book-button').disabled = activeJob !== null; form.setAttribute('aria-busy','false');
    }
  });
  let listRequest = 0;
  async function loadBookings() {
    const current = ++listRequest, content = $('bookings-content');
    $('refresh-bookings').disabled = true; content.setAttribute('aria-busy','true');
    content.replaceChildren(element('p','Loading your bookings…','small'));
    try {
      const {data} = await request('/api/bookings');
      if (current !== listRequest) return;
      content.replaceChildren();
      if (!data.bookings.length) {
        const empty = element('div','','empty');
        empty.append(element('h2','No confirmed bookings yet'), element('p','Saved reservations will appear here.'));
        const link = element('a','Book a table','secondary'); link.href='#book'; empty.append(link); content.append(empty);
      }
      for (const booking of data.bookings) {
        const item = element('article','','booking-item'), details = element('div');
        details.append(element('h2',booking.customer), element('p',`${booking.date} · ${booking.time} · ${booking.party_size} ${booking.party_size === 1 ? 'guest' : 'guests'}`));
        item.append(details, element('span','Confirmed','badge')); content.append(item);
      }
    } catch (error) {
      if (current === listRequest) content.replaceChildren(element('p', error.message + ' Use Refresh bookings to try again.'));
    } finally {
      if (current === listRequest) { content.setAttribute('aria-busy','false'); $('refresh-bookings').disabled = false; }
    }
  }
  function navigate() {
    const listing = location.hash === '#bookings';
    $('book-view').hidden = listing; $('bookings-view').hidden = !listing;
    for (const id of ['nav-book','nav-bookings']) $(id).removeAttribute('aria-current');
    $(listing ? 'nav-bookings' : 'nav-book').setAttribute('aria-current','page');
    if (listing) loadBookings();
  }
  $('refresh-bookings').addEventListener('click',loadBookings);
  window.addEventListener('hashchange',navigate); navigate();
</script>
</body></html>'''


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True

    def __init__(self, address, service, qa_token):
        if address[0] != "127.0.0.1":
            raise ValueError("This simulation binds only to 127.0.0.1.")
        if not qa_token:
            raise ValueError("A nonempty QA token is required.")
        self.service, self.qa_token = service, qa_token
        self.instance_id = os.environ.get("FALSEGREEN_INSTANCE_ID", "")
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "FalseGreen/1.0"

    def _send(self, status, data):
        is_html = isinstance(data, str)
        body = data.encode("utf-8") if is_html else json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if is_html else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _local_request(self):
        # Validate Host as well as peer address to reject DNS rebinding.
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
            authority = urlsplit("//" + self.headers.get("Host", ""))
            if (authority.hostname not in ("localhost", "127.0.0.1")
                    or authority.port != self.server.server_port
                    or authority.username is not None or authority.path):
                return False
            origin = self.headers.get("Origin")
            if origin:
                parsed = urlsplit(origin)
                if (parsed.scheme != "http" or parsed.netloc != authority.netloc
                        or parsed.path or parsed.query or parsed.fragment):
                    return False
            return True
        except ValueError:
            return False

    def do_GET(self):
        if not self._local_request():
            self._send(403, {"error": "Local same-origin requests only."})
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._send(200, HTML)
        elif path == "/healthz":
            # FALSEGREEN_V3_CONTRACT: fresh server identity prevents stale-process results.
            self._send(200, {"app": "falsegreen", "ok": self.server.service.worker.is_alive(),
                             "simulation": True, "instance_id": getattr(self.server, "instance_id", "")})
        elif path == "/qa/last-outcome":
            provided = self.headers.get("X-QA-Token", "")
            if not hmac.compare_digest(provided.encode(), self.server.qa_token.encode()):
                self._send(401, {"error": "QA authentication required."})
                return
            self._send(200, self.server.service.last_outcome())
        elif path == "/api/bookings":
            self._send(200, {"bookings": self.server.service.bookings()})
        elif path.startswith("/api/bookings/"):
            job = self.server.service.status(path[len("/api/bookings/"):])
            self._send(200 if job else 404, job or {"error": "Booking not found."})
        else:
            self._send(404, {"error": "Not found."})

    def do_POST(self):
        if not self._local_request():
            self._send(403, {"error": "Local same-origin requests only."})
            return
        path = urlsplit(self.path).path
        if path in ("/qa/reset", "/qa/fail-next"):
            provided = self.headers.get("X-QA-Token", "")
            if not hmac.compare_digest(provided.encode(), self.server.qa_token.encode()):
                self._send(401, {"error": "QA authentication required. Send X-QA-Token."})
                return
            if path == "/qa/reset":
                self.server.service.reset()
                self._send(200, {"ok": True})
            else:
                self.server.service.arm_failure()
                self._send(200, {"ok": True, "fail_next": True})
            return
        if path != "/api/bookings":
            self._send(404, {"error": "Not found."})
            return
        if self.headers.get_content_type() != "application/json":
            self._send(415, {"error": "Use Content-Type: application/json."})
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Transfer encoding is not supported.")
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 8192:
                raise ValueError("Request body must contain 1–8192 bytes.")
            self.connection.settimeout(5)
            data = json.loads(self.rfile.read(size))
            job = self.server.service.accept(data)
        except (ValueError, UnicodeError) as error:
            self._send(400, {"error": str(error)})
            return
        except (TimeoutError, OSError):
            self._send(408, {"error": "Request body timed out."})
            return
        except RuntimeError as error:
            self._send(503, {"error": str(error)})
            return
        self._send(202, {"id": job["id"], "status": "pending",
                         "status_url": "/api/bookings/" + job["id"]})

    def log_message(self, format, *args):
        # Never log request bodies or QA authentication tokens.
        super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    token = os.environ.get("QA_TOKEN") or secrets.token_urlsafe(32)
    service = BookingService(Path(__file__).resolve().parent / "bookings.sqlite3")
    try:
        server = LocalServer(("127.0.0.1", args.port), service, token)
    except BaseException:
        service.close()
        raise

    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    print(f"FALSE GREEN · controlled local simulation · http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Local QA only — X-QA-Token: {token}", flush=True)
    print("REPAIR stage: HTTP 202 stays pending until the worker reports a durable outcome. No real reservations.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
