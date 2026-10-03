/* Local, resumable tutorials. Reading a lesson never changes a save. */
(() => {
  const lessons = [
    ['start','01 / START',"Getting started: run a health check",'dashboard',[
      "After the game finishes saving, select that save in the overview. Refresh the file list if unsure.",
      "Run the no-JSON health check. Address critical issues before warnings. The score measures inspectable structure, not guaranteed operation.",
      "For timetable data, pause and save in game, keep it paused and export Timetable Export JSON. Refresh the toolkit, select the matching save and export, then Verify save against game export. The toolkit cannot perform this in-game export for you."]],
    ['batch','02 / PLAN',"Select multiple lines and configure them together",'workspace',[
      "Read the selected save, search timetable, line or train names, and select independent operating timetables. Line templates are hidden by default to avoid accidental edits.",
      "Fill only the days, first departure, depot-return time and per-train offsets you want to change. Blank times retain their original values. A single-stop line is not necessarily a depot; confirm it first.",
      "Preview differences for each timetable before creating a new save. Per-train offsets do not guarantee stable actual headways. Removing weekends does not terminate an infinite Friday loop; depot return or an ending connection is still needed. Use the full editor for complex timetables."]],
    ['editor','03 / EDIT',"Editor: changes, undo and drafts",'timetable',[
      "Open the full operating-rule editor and choose a timetable. Entry time controls how a train joins the line; the timing point determines where it waits.",
      "Undo or redo the last 20 edits. Drafts are keyed by save contents and timetable ID, so changed saves do not receive an unrelated draft.",
      "Check weekdays/weekends, overnight times and single-run depot-return orders before writing a copy. Time-window presets accept only compatible simple timetables."]],
    ['accept','04 / VERIFY',"In-game verification: a successful write is not enough」",'workspace',[
      "Keep the original save. Load the newly generated file in game; do not overwrite the original directly.",
      "Check first depot departure, normal service, peak transitions, final depot return and next-day shifts. Watch timing stops, signal waits and repeated starts in X seconds.",
      "After checking operation, pause the game, save the current copy and export timetable data. Refresh the toolkit and verify that pair under Tasks and verification. Loaded / operated are your confirmations, not automatic checks."]],
    ['diagnostic','05 / DIAGNOSE',"How do I troubleshoot dispatch failures or busy tracks?",'workspace',[
      "Check the weekly plan for overlapping shifts and unassigned trains, then inspect actual depot access, capacity and train lengths. Planned depot time does not prove a train enters the depot.",
      "The diagnostic assistant can install a read-only logging mod. Enable it in game, bind Toolkit read-only diagnostic to a small number of test trains, and enable script logging.",
      "After running, copy NIMBY_DIAG Paste records into the diagnostic assistant. SIGNAL_WAIT means waiting at a signal, not proof of a deadlock. Turn logging off after testing to reduce overhead."]],
    ['corridor','06 / ANALYSE',"Shared-track headways, depot capacity and operating rankings",'workspace',[
      "For shared-track coordination, select adjacent stop IDs in the same direction and enter branch running times to the shared entry. This produces a downloadable target departure sequence CSV.",
      "Specify actual depot capacity before reviewing peak occupancy and overruns. Unknown deadhead times, routing and live occupancy still require in-game checks.",
      "Operating rankings use Accounting TSV, not timetable JSON. Place it in the save directory, refresh and select it. Compare only matching statistical periods and object granularity. Missing data is not zero; the proportion of full departures is not average occupancy."]],
    ['cleanup','07 / HOUSEKEEPING',"Copy cleanup and permanent protection",'cleanup',[
      "Preview cleanup first. Protect copies you want to keep permanently, then choose retention counts and ages. Copies with missing creation records or changed contents are skipped.",
      "Automatic cleanup is off by default. When enabled, startup moves eligible files to Recycle Bin without asking each time. Manual cleanup requires a confirmed preview. Permanent protection uses a matching .keep file; move it with the save.",
      "History and project settings are stored in your user configuration directory. Updating the toolkit does not migrate, repair or delete game saves."]],
    ['update','08 / UPDATE',"Automatic checks; update after confirmation",'dashboard',[
      "Check for updates reads the stable GitHub release. With startup checking enabled, cached update checks run on startup. Updates are never installed silently.",
      "Choose Download update and restart. The updater checks the ZIP checksum and every listed file, waits for the current window to exit, then replaces program files.",
      "Use an extracted portable release. Git source checkouts are not overwritten by the updater. If an older version lacks an update button, download a portable release manually once. Failed installs attempt rollback. If restoration is incomplete, stop using the app, retain logs and backups, and extract a complete package again."]],
    ['map','09 / MAP',"Create a metro network map",'map',[
      "Pause the game, save and export timetable data. On Route maps, load lines from game timetable data and select the lines to display.",
      "Search by line name, number or station; sort by A–Z, Z–A, number, stop count or selected-first. Filtering retains selections; filtered-result buttons affect only visible entries. Metro maps identify branches using names, numbers, colors and shared sections. Shared trunks are drawn once; ordinary shared stops are not branch interchanges. Override grouping manually or restore automatic grouping, including hidden selections. True interchanges use circles or capsules. Same-name stations with different IDs stay separate; missing-coordinate sections do not get invented connections.",
      "Choose Urban metro or Railway overview, or use Grid layout for horizontal/vertical connections. Orient the map horizontally, vertically or approximately geographically. Labels follow lines. Use 100%, 150% or 200% zoom and adjust canvas size, spacing and font size. SVG saves the drawing; map JSON retains original operating lines and display groups. Both use this page's export folder. The schematic is not to geographic scale and does not change game tracks."]]
  ];
  const faq = [
    ["Where do I get the timetable JSON?","Use NIMBY Rails' in-game timetable export, not automatic capture by the toolkit. Pause and save, then keep the game paused while exporting. Refresh files and select the JSON whose name contains Timetable Export. Toolkit maps, reports and plan JSON are not substitutes."],
    ["Why does a fresh JSON export still not match?","Confirm the game saved the same state represented by the export. The workspace checks recent candidates and explains mismatches. Do not rename files or ignore differing IDs to bypass protection."],
    ["Why does dispatch keep restarting every few seconds?","Shift position, timing, line entry or connections may not satisfy the requirements. Check the game's exact reason and logs, then inspect depot and passenger-service orders. Do not hide the problem with automatic running."],
    ["Timetable garage join Does this build a depot automatically?","No. This extension changes shift matching for existing trains. It does not build tracks, repair disconnected rails, increase capacity or bypass signals. Check train positions and timetable conditions first."],
    ["Do more CPU cores always make tasks faster?","Reading and matching run in the background. Matching uses at most two workers to control memory. Save writes remain mutually exclusive and cannot be forcibly cancelled because interruption increases corruption risk."],
    ["How can I make the interface easier to read?","Comfortable reading enlarges dense editor fields. Use Tab to navigate and Ctrl+K to find features. Tutorial progress stays on this computer; marking a lesson read never runs its actions."]
  ];
  const section = document.createElement('section'); section.id='view-learn'; section.className='view';
  section.innerHTML = `<div class="learn-hero"><div><p class="eyebrow aqua">NIMBY TOOLKIT / FIELD GUIDE</p><h2>A clear next step for every change.</h2><p>Start with a save, understand its plan, preview changes and verify in game. Nine short tutorials; return whenever you like.</p><span class="learn-progress" id="learn-progress" role="status">0 / 9 Read</span></div><svg class="learn-network" viewBox="0 0 260 170" fill="none" aria-hidden="true"><path d="M8 25H74L152 105H248M8 85H80L147 25H248M8 145H110L180 75H248" stroke="#385765" stroke-width="12" stroke-linecap="round"/><path d="M8 25H74L152 105H248" stroke="#51ddc2" stroke-width="4"/><path d="M8 85H80L147 25H248" stroke="#7eacff" stroke-width="4"/><path d="M8 145H110L180 75H248" stroke="#efbc6d" stroke-width="4"/><g fill="#142531" stroke="#e3edf2" stroke-width="3"><circle cx="38" cy="25" r="6"/><circle cx="112" cy="64" r="9"/><circle cx="194" cy="105" r="6"/><circle cx="207" cy="25" r="6"/><circle cx="69" cy="145" r="6"/><circle cx="217" cy="75" r="6"/></g></svg></div>
    <div class="learn-warning">Safety first: preview, then write a copy. Passing structural checks ≠ Train operation checked. Only you decide whether to replace the main save after in-game verification.</div>
    <div class="learn-toolbar"><input type="search" id="learn-search" placeholder="Search tutorials, e.g. depot, update, JSON…" aria-label="Search tutorials"><label class="learn-density"><input type="checkbox" id="learn-readable">Comfortable reading</label></div>
    <div class="learn-grid">${lessons.map(([id,num,title,view,steps])=>`<article class="learn-card" data-lesson="${id}"><span class="learn-number">${num}</span><h3>${escapeHtml(title)}</h3><ol>${steps.map(s=>`<li>${escapeHtml(s)}</li>`).join('')}</ol><div class="learn-actions"><button class="secondary-button" type="button" data-learn-view="${view}">Open ${escapeHtml(viewMeta[view][1])} →</button><label><input type="checkbox" data-learn-done="${id}">I understand</label></div></article>`).join('')}</div>
    <p id="learn-empty" hidden role="status">No matching tutorials. Try depot, save or update」.</p>
    <article class="panel learn-faq"><h3>Troubleshooting: start here</h3>${faq.map(([q,a])=>`<details><summary>${escapeHtml(q)}</summary><p>${escapeHtml(a)}</p></details>`).join('')}</article>`;
  document.querySelector('main').append(section);
  let prefs={done:[],readable:false}, changed=false, queue=Promise.resolve();
  function render(){
    section.querySelectorAll('[data-learn-done]').forEach(el=>{el.checked=prefs.done.includes(el.dataset.learnDone);el.closest('.learn-card').classList.toggle('done',el.checked);});
    $('#learn-progress').textContent=`${prefs.done.length} / ${lessons.length} Read`;
    $('#learn-readable').checked=prefs.readable;document.body.classList.toggle('readable',prefs.readable);
  }
  function persist(){changed=true;const patch=JSON.parse(JSON.stringify(prefs));queue=queue.catch(()=>{}).then(()=>api('/api/workspace/state',{method:'POST',body:JSON.stringify({key:'tutorial-v1',patch})})).catch(()=>toast("Progress could not be saved; you can continue reading.",true));}
  section.addEventListener('click',e=>{const b=e.target.closest('[data-learn-view]');if(b)switchView(b.dataset.learnView);});
  section.addEventListener('change',e=>{
    if(e.target.matches('[data-learn-done]')){prefs.done=[...section.querySelectorAll('[data-learn-done]:checked')].map(el=>el.dataset.learnDone);render();persist();}
    if(e.target.id==='learn-readable'){prefs.readable=e.target.checked;render();persist();}
  });
  $('#learn-search').addEventListener('input',e=>{let visible=0;const q=e.target.value.trim().toLowerCase();section.querySelectorAll('.learn-card').forEach(el=>{el.hidden=!el.textContent.toLowerCase().includes(q);if(!el.hidden)visible++;});$('#learn-empty').hidden=visible>0;});
  $('#open-tutorial').addEventListener('click',()=>switchView('learn'));
  api('/api/workspace/state',{method:'POST',body:JSON.stringify({key:'tutorial-v1'})}).then(r=>{if(changed)return;const ids=new Set(lessons.map(l=>l[0]));prefs={done:[...new Set((Array.isArray(r.value?.done)?r.value.done:[]).filter(id=>ids.has(id)))],readable:r.value?.readable===true};render();}).catch(()=>{});
})();
