import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api } from '../api'
import type { Assessment, Supplier } from '../types'
import { RiskBadge } from '../components/RiskBadge'
import { EmptyState } from '../components/EmptyState'

const currency = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

const supplierSchema = z.object({
  legal_name: z.string().min(2).max(160),
  category: z.string().min(2).max(80),
  contact: z.string().email(),
  city: z.string().min(2).max(80),
  state: z.string().min(2).max(80),
  business_age_years: z.coerce.number().min(0).max(100),
  registration_identifier: z.string().min(3).max(80),
  payment_beneficiary: z.string().min(2).max(160),
  payment_reference_masked: z.string().min(4).max(80),
  source: z.string().min(2).max(80),
  notes: z.string().max(1000).optional(),
})
type SupplierFormData = z.infer<typeof supplierSchema>

interface SuppliersPageProps {
  assessments: Assessment[]
  onSelectAssessment: (a: Assessment) => void
  canCreate?: boolean
}

export function SuppliersPage({ assessments, onSelectAssessment, canCreate = true }: SuppliersPageProps) {
  const [search, setSearch] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [selectedSupplier, setSelectedSupplier] = useState<Supplier | null>(null)
  const qc = useQueryClient()

  const suppliersQuery = useQuery({
    queryKey: ['suppliers', search],
    queryFn: () => api.suppliers(search),
    staleTime: 30_000,
  })

  const { register, handleSubmit, reset, setValue, formState: { errors, isSubmitting } } = useForm<SupplierFormData>({
    resolver: zodResolver(supplierSchema)
  })

  const [ocrMessage, setOcrMessage] = useState('')
  const ocrMutation = useMutation({
    mutationFn: (file: File) => api.extractDocument(file, 'business_document'),
    onSuccess: data => {
      setOcrMessage('Extracted! Check the form below.')
      if (data.extracted_fields?.supplier) setValue('legal_name', data.extracted_fields.supplier)
      if (data.extracted_fields?.gstin) setValue('registration_identifier', data.extracted_fields.gstin)
      if (data.extracted_fields?.city) setValue('city', data.extracted_fields.city)
      if (data.extracted_fields?.contact) setValue('contact', data.extracted_fields.contact)
      if (data.extracted_fields?.state) setValue('state', data.extracted_fields.state)
      if (data.extracted_fields?.payment_beneficiary) setValue('payment_beneficiary', data.extracted_fields.payment_beneficiary)
      if (data.extracted_fields?.payment_reference_masked) setValue('payment_reference_masked', data.extracted_fields.payment_reference_masked)
      if (data.extracted_fields?.category) setValue('category', data.extracted_fields.category)
      if (data.extracted_fields?.source) setValue('source', data.extracted_fields.source)
      if (data.extracted_fields?.notes) setValue('notes', data.extracted_fields.notes)
      if (data.extracted_fields?.business_age_years) setValue('business_age_years', data.extracted_fields.business_age_years)
    },
    onError: (e: Error) => setOcrMessage(e.message)
  })

  const createMutation = useMutation({
    mutationFn: (data: SupplierFormData) => api.createSupplier(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['suppliers'] })
      setShowForm(false)
      reset()
    },
  })

  const suppliers = suppliersQuery.data ?? []
  const latestRisk = (supplierId: string) => assessments.filter(a => a.supplier_id === supplierId)[0]

  return (
    <>
      {showForm && (
        <div className="modal">
          <form className="form" onSubmit={handleSubmit(data => createMutation.mutate(data))}>
            <div className="form-head">
              <div><h2>Add supplier</h2><p>All fields are required.</p></div>
              <button type="button" className="quiet icon-btn" onClick={() => setShowForm(false)}><X size={18} /></button>
            </div>
            <div style={{ background: '#F0F9FF', padding: '12px 16px', margin: '0 24px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
              <div>
                <strong>Auto-fill with OCR</strong>
                <div style={{ fontSize: '0.85rem', color: '#64748B' }}>Upload an invoice to automatically populate details.</div>
              </div>
              <input type="file" accept="application/pdf,image/png,image/jpeg" style={{ marginLeft: 'auto', maxWidth: 200 }}
                onChange={e => { const f = e.target.files?.[0]; if (f) ocrMutation.mutate(f) }} />
              {ocrMutation.isPending && <small>Scanning...</small>}
              {ocrMessage && <small style={{ color: ocrMutation.isError ? 'red' : 'green' }}>{ocrMessage}</small>}
            </div>
            <div className="form-grid">
              <label>Legal name<input {...register('legal_name')} placeholder="Acme Industries Pvt Ltd" />{errors.legal_name && <span className="field-error">{errors.legal_name.message}</span>}</label>
              <label>Category<input {...register('category')} placeholder="Industrial supplies" />{errors.category && <span className="field-error">{errors.category.message}</span>}</label>
              <label>Contact email<input {...register('contact')} type="email" placeholder="accounts@supplier.com" />{errors.contact && <span className="field-error">{errors.contact.message}</span>}</label>
              <label>City<input {...register('city')} placeholder="Mumbai" />{errors.city && <span className="field-error">{errors.city.message}</span>}</label>
              <label>State<input {...register('state')} placeholder="Maharashtra" />{errors.state && <span className="field-error">{errors.state.message}</span>}</label>
              <label>Business age (years)<input {...register('business_age_years')} type="number" step="0.5" placeholder="5" />{errors.business_age_years && <span className="field-error">{errors.business_age_years.message}</span>}</label>
              <label>Registration / GSTIN<input {...register('registration_identifier')} placeholder="22AAAAA0000A1Z5" />{errors.registration_identifier && <span className="field-error">{errors.registration_identifier.message}</span>}</label>
              <label>Payment beneficiary name<input {...register('payment_beneficiary')} placeholder="Acme Industries Pvt Ltd" />{errors.payment_beneficiary && <span className="field-error">{errors.payment_beneficiary.message}</span>}</label>
              <label>Account number (masked)<input {...register('payment_reference_masked')} placeholder="XXXX 0000" />{errors.payment_reference_masked && <span className="field-error">{errors.payment_reference_masked.message}</span>}</label>
              <label>Source of supplier<input {...register('source')} placeholder="Trade referral" />{errors.source && <span className="field-error">{errors.source.message}</span>}</label>
              <label style={{ gridColumn: '1 / -1' }}>Notes (optional)<textarea {...register('notes')} rows={2} placeholder="Additional context" /></label>
            </div>
            {createMutation.error && <p className="error">{(createMutation.error as Error).message}</p>}
            <div className="form-actions">
              <button type="button" className="quiet" onClick={() => setShowForm(false)}>Cancel</button>
              <button className="primary" disabled={isSubmitting || createMutation.isPending}>
                {createMutation.isPending ? 'Saving...' : 'Create supplier'}
              </button>
            </div>
          </form>
        </div>
      )}

      {selectedSupplier && (
        <SupplierDetailPanel
          supplier={selectedSupplier}
          assessments={assessments}
          onClose={() => setSelectedSupplier(null)}
          onSelectAssessment={onSelectAssessment}
          onDeleted={() => { setSelectedSupplier(null); qc.invalidateQueries({ queryKey: ['suppliers'] }) }}
          onUpdated={(updated) => { setSelectedSupplier(updated); qc.invalidateQueries({ queryKey: ['suppliers'] }) }}
          canCreate={canCreate}
        />
      )}

      <section className="panel">
        <div className="panel-title">
          <div><h2>Supplier directory</h2><p>All suppliers in your workspace. Click a row to view details.</p></div>
          <div className="panel-controls">
            <input className="search-input" placeholder="Search suppliers..." value={search} onChange={e => setSearch(e.target.value)} />
            <button className="primary" onClick={() => setShowForm(true)}><Plus size={16} /> Add supplier</button>
          </div>
        </div>
        {suppliersQuery.isLoading && <div className="skeleton-list">{[1,2,3].map(i => <div key={i} className="skeleton-row" />)}</div>}
        {suppliersQuery.error && <p className="error">Unable to load suppliers: {(suppliersQuery.error as Error).message}</p>}
        {!suppliersQuery.isLoading && suppliers.length === 0 && (
          <EmptyState title="No suppliers yet" description="Add your first supplier to begin risk assessment."
            action={<button className="primary" onClick={() => setShowForm(true)}><Plus size={16} /> Add supplier</button>} />
        )}
        {suppliers.length > 0 && (
          <>
            <span className="count">{suppliers.length} suppliers</span>
            <table>
              <thead><tr><th>Supplier</th><th>Category</th><th>Location</th><th>Business age</th><th>Latest risk</th></tr></thead>
              <tbody>
                {suppliers.map(s => {
                  const latest = latestRisk(s.id)
                  return (
                    <tr key={s.id} onClick={() => setSelectedSupplier(s)} style={{ cursor: 'pointer' }}>
                      <td><b>{s.legal_name}</b><small>{s.status}</small></td>
                      <td>{s.category}</td>
                      <td>{s.city}, {s.state}</td>
                      <td>{s.business_age_years} yrs</td>
                      <td>{latest ? <RiskBadge risk={latest.risk_category} score={latest.risk_score} /> : <span className="muted">Not assessed</span>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </>
        )}
      </section>
    </>
  )
}

function SupplierDetailPanel({
  supplier, assessments, onClose, onSelectAssessment, onDeleted, onUpdated, canCreate,
}: {
  supplier: Supplier
  assessments: Assessment[]
  onClose: () => void
  onSelectAssessment: (a: Assessment) => void
  onDeleted: () => void
  onUpdated: (s: Supplier) => void
  canCreate: boolean
}) {
  const qc = useQueryClient()
  const [editMode, setEditMode] = useState(false)

  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<SupplierFormData>({
    resolver: zodResolver(supplierSchema),
    defaultValues: {
      legal_name: supplier.legal_name,
      category: supplier.category,
      contact: supplier.contact,
      city: supplier.city,
      state: supplier.state,
      business_age_years: supplier.business_age_years,
      registration_identifier: supplier.registration_identifier,
      payment_beneficiary: supplier.payment_beneficiary,
      payment_reference_masked: supplier.payment_reference_masked,
      source: supplier.source,
      notes: supplier.notes ?? '',
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data: SupplierFormData) => api.patchSupplier(supplier.id, data),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['suppliers'] })
      onUpdated(updated)
      setEditMode(false)
      reset({ ...updated, notes: updated.notes ?? '' })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteSupplier(supplier.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['suppliers'] }); onDeleted() },
  })

  const supplierAssessments = assessments.filter(a => a.supplier_id === supplier.id)

  return (
    <div className="detail-panel">
      <div className="detail-head">
        <div>
          <h2>{supplier.legal_name}</h2>
          <p>{supplier.category} &middot; {supplier.city}, {supplier.state}</p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {canCreate && (
            <button className="quiet" onClick={() => setEditMode(e => !e)}>
              &#9998; {editMode ? 'Cancel' : 'Edit'}
            </button>
          )}
          <button className="quiet danger-quiet" disabled={deleteMutation.isPending}
            onClick={() => {
              if (window.confirm(`Permanently delete "${supplier.legal_name}" and all their history? This is logged but cannot be undone.`)) {
                deleteMutation.mutate()
              }
            }}>
            {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
          </button>
          <button className="quiet icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
      </div>

      {editMode && (
        <form className="form" style={{ margin: '0 0 16px', border: '1px solid #E2E8F0', borderRadius: 8, padding: 16 }}
          onSubmit={handleSubmit(data => updateMutation.mutate(data))}>
          <h4 style={{ margin: '0 0 12px' }}>Edit supplier details</h4>
          <div className="form-grid">
            <label>Legal name<input {...register('legal_name')} />{errors.legal_name && <span className="field-error">{errors.legal_name.message}</span>}</label>
            <label>Category<input {...register('category')} />{errors.category && <span className="field-error">{errors.category.message}</span>}</label>
            <label>Contact email<input {...register('contact')} type="email" />{errors.contact && <span className="field-error">{errors.contact.message}</span>}</label>
            <label>City<input {...register('city')} />{errors.city && <span className="field-error">{errors.city.message}</span>}</label>
            <label>State<input {...register('state')} />{errors.state && <span className="field-error">{errors.state.message}</span>}</label>
            <label>Business age (years)<input {...register('business_age_years')} type="number" step="0.5" />{errors.business_age_years && <span className="field-error">{errors.business_age_years.message}</span>}</label>
            <label>Registration / GSTIN<input {...register('registration_identifier')} />{errors.registration_identifier && <span className="field-error">{errors.registration_identifier.message}</span>}</label>
            <label>Payment beneficiary<input {...register('payment_beneficiary')} />{errors.payment_beneficiary && <span className="field-error">{errors.payment_beneficiary.message}</span>}</label>
            <label>Account (masked)<input {...register('payment_reference_masked')} />{errors.payment_reference_masked && <span className="field-error">{errors.payment_reference_masked.message}</span>}</label>
            <label>Source<input {...register('source')} />{errors.source && <span className="field-error">{errors.source.message}</span>}</label>
            <label style={{ gridColumn: '1 / -1' }}>Notes<textarea {...register('notes')} rows={2} /></label>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button type="submit" className="primary" disabled={isSubmitting || updateMutation.isPending}>
              {updateMutation.isPending ? 'Saving...' : 'Save changes'}
            </button>
            <button type="button" className="quiet" onClick={() => setEditMode(false)}>Cancel</button>
          </div>
          {updateMutation.isError && <p className="error">{(updateMutation.error as Error).message}</p>}
        </form>
      )}

      <div className="detail-grid">
        <div className="detail-section">
          <h3>Identity</h3>
          <dl>
            <dt>Registration ID</dt><dd>{supplier.registration_identifier}</dd>
            <dt>Contact</dt><dd>{supplier.contact}</dd>
            <dt>Source</dt><dd>{supplier.source}</dd>
            <dt>Business age</dt><dd>{supplier.business_age_years} years</dd>
            <dt>Status</dt><dd><span className="badge">{supplier.status}</span></dd>
            {supplier.notes && <><dt>Notes</dt><dd>{supplier.notes}</dd></>}
          </dl>
        </div>
        <div className="detail-section">
          <h3>Risk history</h3>
          {supplierAssessments.length === 0 ? (
            <p className="muted">No assessments yet for this supplier.</p>
          ) : (
            <table>
              <thead><tr><th>ID</th><th>Amount</th><th>Risk</th><th>Date</th></tr></thead>
              <tbody>
                {supplierAssessments.map(a => (
                  <tr key={a.id} onClick={() => onSelectAssessment(a)} style={{ cursor: 'pointer' }}>
                    <td><b>{a.id.slice(-6).toUpperCase()}</b></td>
                    <td>{currency.format(a.amount)}</td>
                    <td><RiskBadge risk={a.risk_category} score={a.risk_score} /></td>
                    <td><small>{new Date(a.created_at).toLocaleDateString('en-IN')}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <DocumentUpload supplierId={supplier.id} />
      </div>
    </div>
  )
}

function DocumentUpload({ supplierId }: { supplierId: string }) {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [documentType, setDocumentType] = useState('invoice')
  const [message, setMessage] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const docs = useQuery({
    queryKey: ['supplier-documents', supplierId],
    queryFn: () => api.supplierDocuments(supplierId)
  })

  const upload = useMutation({
    mutationFn: () => api.uploadDocument(file!, documentType, supplierId),
    onSuccess: data => {
      setMessage(`${data.filename} uploaded successfully.`)
      setFile(null)
      qc.invalidateQueries({ queryKey: ['supplier-documents', supplierId] })
    },
    onError: (e: Error) => setMessage(e.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteDocument(id),
    onMutate: (id) => setDeletingId(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['supplier-documents', supplierId] })
      setDeletingId(null)
    },
    onError: (e: Error) => { setMessage(e.message); setDeletingId(null) },
  })

  return (
    <div className="detail-section">
      <h3>Supplier Memory</h3>
      <p className="muted" style={{ fontSize: '0.85rem', marginBottom: 12 }}>
        Store supporting documents (GST cert, cancelled cheque, MCA registration, quotations). OCR extracts key fields automatically.
      </p>
      {docs.data && docs.data.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {docs.data.map((d: any) => (
            <div key={d.id} className="memory-card">
              <div className="memory-card-header">
                <div><b>{d.filename}</b> <span className="memory-doc-type">({d.document_type})</span></div>
                <button
                  type="button"
                  className="quiet danger-quiet"
                  style={{ fontSize: '0.8rem', padding: '2px 8px' }}
                  disabled={deleteMutation.isPending && deletingId === d.id}
                  onClick={() => {
                    if (window.confirm('Remove this document from memory? This is logged but cannot be undone.')) {
                      deleteMutation.mutate(d.id)
                    }
                  }}
                >
                  {deleteMutation.isPending && deletingId === d.id ? 'Removing...' : 'Remove'}
                </button>
              </div>
              {d.extracted_fields && Object.keys(d.extracted_fields).length > 0 ? (
                <ul className="memory-fields">
                  {Object.entries(d.extracted_fields).map(([k, v]) => <li key={k}><b>{k}:</b> {String(v)}</li>)}
                </ul>
              ) : <div className="muted" style={{ marginTop: 4, fontSize: '0.85rem' }}>No structured data extracted.</div>}
            </div>
          ))}
        </div>
      )}
      <div className="document-upload">
        <select value={documentType} onChange={e => setDocumentType(e.target.value)}>
          <option value="quotation">Quotation</option>
          <option value="invoice">Invoice</option>
          <option value="registration">Registration / Tax Certificate</option>
          <option value="bank_document">Cancelled Cheque / Bank Letter</option>
          <option value="communication">Email / Communication</option>
          <option value="business_document">Business Document</option>
          <option value="other">Other Evidence</option>
        </select>
        <input type="file" accept="application/pdf,image/png,image/jpeg" onChange={e => setFile(e.target.files?.[0] ?? null)} />
        <button className="primary" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>
          {upload.isPending ? 'Processing...' : 'Add to Memory'}
        </button>
        {message && <small className={upload.isError ? 'error' : 'success'} style={{ display: 'block', marginTop: 6 }}>{message}</small>}
      </div>
    </div>
  )
}

