import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import './App.css';

const API_BASE = 'http://127.0.0.1:8000/api';

interface Dataset {
  id: string;
  filename: string;
  version: number;
  total_rows: number;
  valid_rows: number;
  malformed_rows: number;
}

function App() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string>('');
  const [compareDataset, setCompareDataset] = useState<string>('');
  const [compareMode, setCompareMode] = useState(false);
  const [compareData, setCompareData] = useState<any[]>([]);
  
  const [stats, setStats] = useState<any>(null);
  const [preview, setPreview] = useState<any[]>([]);
  const [gestures, setGestures] = useState<string[]>([]);
  const [filter, setFilter] = useState<string>('');
  const [uploading, setUploading] = useState(false);

  // Fetch datasets on load
  useEffect(() => {
    fetch(`${API_BASE}/datasets`)
      .then(res => res.json())
      .then(data => {
        setDatasets(data);
        if (data.length > 0) setSelectedDataset(data[0].id);
        if (data.length > 1) setCompareDataset(data[1].id);
      });
  }, []);

  // Fetch standard data
  useEffect(() => {
    if (!selectedDataset || compareMode) return;
    fetch(`${API_BASE}/datasets/${selectedDataset}/stats`).then(res => res.json()).then(data => setStats(data));

    const url = `${API_BASE}/datasets/${selectedDataset}/preview?page=1&size=10${filter ? `&gesture=${filter}` : ''}`;
    fetch(url).then(res => res.json()).then(data => {
      setPreview(data.records);
      if (!filter) setGestures(data.gestures);
    });
  }, [selectedDataset, filter, compareMode]);

  // Fetch compare data
  useEffect(() => {
    if (!compareMode || !selectedDataset || !compareDataset) return;
    fetch(`${API_BASE}/compare?base_id=${selectedDataset}&compare_id=${compareDataset}`)
      .then(res => res.json())
      .then(data => setCompareData(data));
  }, [selectedDataset, compareDataset, compareMode]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
      if (res.ok) {
        const newDs = await res.json();
        alert(`Uploaded! (Version ${newDs.version})`);
        const list = await fetch(`${API_BASE}/datasets`).then(r => r.json());
        setDatasets(list);
        setSelectedDataset(newDs.dataset_id);
      } else {
        const err = await res.json();
        alert(`Error: ${err.detail}`);
      }
    } catch (err) {
      alert('Upload failed. Is backend running?');
    }
    setUploading(false);
  };

  const activeDataset = datasets.find(d => d.id === selectedDataset);

  return (
    <div className="container">
      <header>
        <h1>Gesture Data Explorer</h1>
        <div style={{ display: 'flex', gap: '15px', alignItems: 'center' }}>
          <label>
            <input type="checkbox" checked={compareMode} onChange={e => setCompareMode(e.target.checked)} />
            Compare Mode
          </label>
          <input type="file" accept=".csv" onChange={handleUpload} disabled={uploading} />
        </div>
      </header>

      <main className="dashboard">
        <aside className="sidebar">
          <h2>Upload History</h2>
          <ul className="dataset-list">
            {datasets.map(ds => (
              <li key={ds.id} className={ds.id === selectedDataset ? 'active' : ''}>
                <div onClick={() => { setSelectedDataset(ds.id); setFilter(''); }}>
                  <strong>{ds.filename}</strong> (v{ds.version})
                  <br />
                  <small>{ds.valid_rows} valid / {ds.malformed_rows} malformed</small>
                </div>
              </li>
            ))}
          </ul>
        </aside>

        <section className="content">
          {compareMode ? (
            <div className="card">
              <h2>Compare Datasets</h2>
              <div style={{ display: 'flex', gap: '20px', marginBottom: '20px' }}>
                <div>
                  <label>Base Dataset</label>
                  <select value={selectedDataset} onChange={e => setSelectedDataset(e.target.value)}>
                    {datasets.map(d => <option key={d.id} value={d.id}>{d.filename} v{d.version}</option>)}
                  </select>
                </div>
                <div>
                  <label>Compare To</label>
                  <select value={compareDataset} onChange={e => setCompareDataset(e.target.value)}>
                    {datasets.map(d => <option key={d.id} value={d.id}>{d.filename} v{d.version}</option>)}
                  </select>
                </div>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Gesture</th>
                    <th>Count (Base)</th>
                    <th>Count (Compare)</th>
                    <th>Count Diff</th>
                    <th>Avg Conf Diff</th>
                  </tr>
                </thead>
                <tbody>
                  {compareData.map((row, i) => (
                    <tr key={i}>
                      <td>{row.gesture}</td>
                      <td>{row.count_base}</td>
                      <td>{row.count_compare}</td>
                      <td style={{ color: row.count_diff > 0 ? 'green' : row.count_diff < 0 ? 'red' : 'inherit' }}>
                        {row.count_diff > 0 ? '+' : ''}{row.count_diff}
                      </td>
                      <td>{row.avg_conf_diff.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : activeDataset ? (
            <>
              <div className="card">
                <h2>Dataset Info: {activeDataset.filename}</h2>
                <p>Total Rows: {activeDataset.total_rows} | Valid: {activeDataset.valid_rows} | Malformed: {activeDataset.malformed_rows}</p>
              </div>

              {stats && (
                <div className="card">
                  <h2>Gesture Distribution</h2>
                  <div style={{ height: 300 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={stats.chart_data}>
                        <XAxis dataKey="name" />
                        <YAxis />
                        <Tooltip />
                        <Bar dataKey="value" fill="#646cff" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h2>Preview</h2>
                  <select value={filter} onChange={e => setFilter(e.target.value)}>
                    <option value="">All Gestures</option>
                    {gestures.map(g => <option key={g} value={g}>{g}</option>)}
                  </select>
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>Timestamp</th>
                      <th>Gesture</th>
                      <th>Confidence</th>
                      <th>Duration (ms)</th>
                      <th>Hand</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((row, i) => (
                      <tr key={i}>
                        <td>{row.timestamp}</td>
                        <td>{row.gesture}</td>
                        <td>{row.confidence}</td>
                        <td>{row.duration_ms}</td>
                        <td>{row.hand}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <a href={`${API_BASE}/datasets/${selectedDataset}/export${filter ? `?gesture=${filter}` : ''}`} className="button" target="_blank">
                  Export CSV
                </a>
              </div>
            </>
          ) : <p>Upload a dataset to begin.</p>}
        </section>
      </main>
    </div>
  );
}

export default App;