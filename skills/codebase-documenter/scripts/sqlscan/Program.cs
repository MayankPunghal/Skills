// sqlscan: parses T-SQL with Microsoft's ScriptDom (the parser behind SSDT / sqlpackage) and prints JSON facts.
//
// Input (stdin): JSON array of items  {"id": "...", "path": "file.sql"}  or  {"id": "...", "text": "SELECT ..."}
// Output (stdout): JSON array, one result per item:
//   id, parser, errors[{line,col,message}],
//   objects[]   CREATE/ALTER of TABLE, VIEW, PROCEDURE, FUNCTION, TRIGGER, TYPE, SEQUENCE, SYNONYM, INDEX:
//               kind, name, line, end_line, lines, params, returns, columns, primary_key, foreign_keys, indexes,
//               on_object, trigger_type, trigger_events, reads, writes[{name,op}], calls, functions, temp_tables,
//               result_sets, return_value, dynamic_sql, constructs{label:count}
//   script      the same reference/construct facts for statements outside any object (seed scripts, inline queries),
//               plus statements[] (statement kinds in order)
// Names are schema-qualified as written (brackets and quotes removed); three/four-part names keep their database/server.
using System.Text.Json;
using Microsoft.SqlServer.TransactSql.ScriptDom;

static class Program
{
    static int Main(string[] args)
    {
        var input = Console.In.ReadToEnd();
        var items = JsonSerializer.Deserialize<List<Dictionary<string, string>>>(input) ?? new();
        var parserType = typeof(TSqlParser).Assembly.GetTypes()
            .Where(t => !t.IsAbstract && typeof(TSqlParser).IsAssignableFrom(t) && t.Name.StartsWith("TSql") && t.Name.EndsWith("Parser"))
            .OrderByDescending(t => int.TryParse(new string(t.Name.Where(char.IsDigit).ToArray()), out var n) ? n : 0)
            .First();
        var results = new object[items.Count];
        Parallel.For(0, items.Count, i =>
        {
            var it = items[i];
            try { results[i] = Scan(parserType, it); }
            catch (Exception ex) { results[i] = new Dictionary<string, object?> { ["id"] = it.GetValueOrDefault("id"), ["fatal"] = ex.GetType().Name + ": " + ex.Message }; }
        });
        Console.Out.Write(JsonSerializer.Serialize(results));
        return 0;
    }

    static Dictionary<string, object?> Scan(Type parserType, Dictionary<string, string> it)
    {
        var text = it.TryGetValue("text", out var t) ? t : File.ReadAllText(it["path"]);
        var parser = (TSqlParser)Activator.CreateInstance(parserType, new object[] { true })!;  // initialQuotedIdentifiers
        var fragment = parser.Parse(new StringReader(text), out IList<ParseError> errors);
        var objects = new List<Dictionary<string, object?>>();
        var script = new Collector();
        var kinds = new List<string>();
        if (fragment is TSqlScript s)
        {
            foreach (var batch in s.Batches)
                foreach (var st in batch.Statements)
                {
                    kinds.Add(st.GetType().Name.Replace("Statement", ""));
                    var o = Objects.Describe(st);
                    if (o is null) { st.Accept(script); continue; }
                    var c = new Collector();
                    st.Accept(c);
                    foreach (var (k, v) in c.Facts()) o[k] = v;
                    objects.Add(o);
                }
        }
        var res = new Dictionary<string, object?>
        {
            ["id"] = it.GetValueOrDefault("id"),
            ["parser"] = parserType.Name,
            ["errors"] = errors.Select(e => new Dictionary<string, object> { ["line"] = e.Line, ["col"] = e.Column, ["message"] = e.Message }).ToList(),
            ["objects"] = objects,
        };
        var sf = script.Facts();
        sf["statements"] = kinds;
        res["script"] = sf;
        return res;
    }
}

static class Util
{
    public static string Name(SchemaObjectName? n) => n is null ? "" :
        string.Join(".", new[] { n.ServerIdentifier, n.DatabaseIdentifier, n.SchemaIdentifier, n.BaseIdentifier }.Where(x => x != null).Select(x => x!.Value));

    public static string Text(TSqlFragment? f)
    {
        if (f is null || f.FirstTokenIndex < 0) return "";
        var toks = f.ScriptTokenStream;
        var sb = new System.Text.StringBuilder();
        for (var i = f.FirstTokenIndex; i <= f.LastTokenIndex && i < toks.Count; i++) sb.Append(toks[i].Text);
        return string.Join(" ", sb.ToString().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }

    public static int EndLine(TSqlFragment f)
    {
        var toks = f.ScriptTokenStream;
        return f.LastTokenIndex >= 0 && f.LastTokenIndex < toks.Count ? toks[f.LastTokenIndex].Line : f.StartLine;
    }

    public static string Col(ColumnReferenceExpression? c) => c?.MultiPartIdentifier?.Identifiers.LastOrDefault()?.Value ?? "";
    public static string Col(ColumnWithSortOrder c) => Col(c.Column);
}

/// <summary>Builds the object record (kind, name, signature, columns...) for a defining statement; null for other statements.</summary>
static class Objects
{
    public static Dictionary<string, object?>? Describe(TSqlStatement st)
    {
        Dictionary<string, object?> O(string kind, SchemaObjectName? name, string verb) => new()
        {
            ["kind"] = kind, ["name"] = Util.Name(name), ["verb"] = verb, ["line"] = st.StartLine,
            ["end_line"] = Util.EndLine(st), ["lines"] = Util.EndLine(st) - st.StartLine + 1,
        };
        string Verb() => st.GetType().Name.StartsWith("CreateOrAlter") ? "create or alter" : st.GetType().Name.StartsWith("Alter") ? "alter" : "create";
        switch (st)
        {
            case CreateTableStatement ct:
            {
                var o = O("TABLE", ct.SchemaObjectName, "create");
                Table(ct, o);
                return o;
            }
            case CreateSecurityPolicyStatement sp:
            {
                var o = O("SECURITY POLICY", sp.Name, "create");
                o["targets"] = sp.SecurityPredicateActions.Select(a => Util.Name(a.TargetObjectName)).Distinct().ToList();
                return o;
            }
            case CreateAggregateStatement ag:
            {
                var o = O("AGGREGATE", ag.Name, "create");
                o["clr"] = true;
                return o;
            }
            case ViewStatementBody v:
            {
                var o = O("VIEW", v.SchemaObjectName, Verb());
                o["columns"] = v.Columns.Select(c => c.Value).ToList();
                o["schemabinding"] = v.ViewOptions.Any(x => x.OptionKind == ViewOptionKind.SchemaBinding);
                return o;
            }
            case ProcedureStatementBody p:
            {
                var o = O("PROCEDURE", p.ProcedureReference?.Name, Verb());
                o["params"] = Params(p.Parameters);
                o["clr"] = p.MethodSpecifier != null;
                return o;
            }
            case FunctionStatementBody f:
            {
                var o = O("FUNCTION", f.Name, Verb());
                o["params"] = Params(f.Parameters);
                o["clr"] = f.MethodSpecifier != null;
                o["returns"] = f.ReturnType switch
                {
                    ScalarFunctionReturnType sr => "scalar " + Util.Text(sr.DataType),
                    SelectFunctionReturnType => "inline table",
                    TableValuedFunctionReturnType tv => "table " + Util.Text(tv.DeclareTableVariableBody?.Definition),
                    _ => f.MethodSpecifier != null ? "clr" : "",
                };
                return o;
            }
            case TriggerStatementBody tr:
            {
                var o = O("TRIGGER", tr.Name, Verb());
                o["on_object"] = Util.Name(tr.TriggerObject?.Name);
                o["trigger_type"] = tr.TriggerType.ToString();
                o["trigger_events"] = tr.TriggerActions.Select(a => a.TriggerActionType.ToString()).ToList();
                return o;
            }
            case CreateTypeTableStatement tt:
            {
                var o = O("TYPE", tt.Name, "create");
                o["type_kind"] = "table";
                o["columns"] = tt.Definition.ColumnDefinitions.Select(Column).ToList();
                return o;
            }
            case CreateTypeUddtStatement ut:
            {
                var o = O("TYPE", ut.Name, "create");
                o["type_kind"] = "alias " + Util.Text(ut.DataType);
                return o;
            }
            case CreateSequenceStatement sq: return O("SEQUENCE", sq.Name, "create");
            case CreateSynonymStatement sy:
            {
                var o = O("SYNONYM", sy.Name, "create");
                o["on_object"] = Util.Name(sy.ForName);
                return o;
            }
            case CreateIndexStatement ix:
            {
                var o = O("INDEX", ix.OnName, "create");
                o["index"] = ix.Name?.Value;
                o["unique"] = ix.Unique;
                o["index_columns"] = ix.Columns.Select(Util.Col).ToList();
                o["include"] = ix.IncludeColumns.Select(Util.Col).ToList();
                o["filter"] = Util.Text(ix.FilterPredicate);
                return o;
            }
            case AlterTableAddTableElementStatement at:
            {
                var o = O("TABLE", at.SchemaObjectName, "alter");
                Constraints(at.Definition?.TableConstraints ?? new List<ConstraintDefinition>(), o);
                o["columns"] = at.Definition?.ColumnDefinitions.Select(Column).ToList();
                return o;
            }
        }
        return null;
    }

    static List<Dictionary<string, object?>> Params(IList<ProcedureParameter> ps) => ps.Select(p => new Dictionary<string, object?>
    {
        ["name"] = p.VariableName.Value, ["type"] = Util.Text(p.DataType),
        ["output"] = p.Modifier == ParameterModifier.Output, ["readonly"] = p.Modifier == ParameterModifier.ReadOnly,
        ["default"] = p.Value is null ? null : Util.Text(p.Value),
    }).ToList();

    static Dictionary<string, object?> Column(ColumnDefinition c) => new()
    {
        ["name"] = c.ColumnIdentifier.Value,
        ["type"] = c.DataType is null ? null : Util.Text(c.DataType),
        ["nullable"] = c.Constraints.OfType<NullableConstraintDefinition>().Select(n => (bool?)n.Nullable).FirstOrDefault(),
        ["identity"] = c.IdentityOptions != null,
        ["computed"] = c.ComputedColumnExpression is null ? null : Util.Text(c.ComputedColumnExpression),
        ["default"] = c.DefaultConstraint is null ? null : Util.Text(c.DefaultConstraint.Expression),
        ["collation"] = c.Collation?.Value,
        ["primary_key"] = c.Constraints.OfType<UniqueConstraintDefinition>().Any(u => u.IsPrimaryKey),
        ["unique"] = c.Constraints.OfType<UniqueConstraintDefinition>().Any(u => !u.IsPrimaryKey),
        ["references"] = c.Constraints.OfType<ForeignKeyConstraintDefinition>().Select(f => Util.Name(f.ReferenceTableName)).FirstOrDefault(),
        ["rowversion"] = c.DataType is SqlDataTypeReference sd && sd.SqlDataTypeOption == SqlDataTypeOption.Timestamp,
    };

    static void Table(CreateTableStatement ct, Dictionary<string, object?> o)
    {
        var def = ct.Definition;
        o["columns"] = def?.ColumnDefinitions.Select(Column).ToList();
        Constraints(def?.TableConstraints ?? new List<ConstraintDefinition>(), o, def?.ColumnDefinitions);
        o["temporal"] = ct.Options.OfType<SystemVersioningTableOption>().Any();
        o["memory_optimized"] = ct.Options.OfType<MemoryOptimizedTableOption>().Any(m => m.OptionState == OptionState.On);
        o["graph"] = ct.AsNode ? "node" : ct.AsEdge ? "edge" : null;
        o["indexes"] = def?.Indexes.Select(i => new Dictionary<string, object?> { ["name"] = i.Name?.Value, ["columns"] = i.Columns.Select(Util.Col).ToList(), ["unique"] = i.Unique }).ToList();
    }

    static void Constraints(IList<ConstraintDefinition> cs, Dictionary<string, object?> o, IList<ColumnDefinition>? cols = null)
    {
        var pk = cs.OfType<UniqueConstraintDefinition>().Where(u => u.IsPrimaryKey).SelectMany(u => u.Columns.Select(Util.Col)).ToList();
        if (pk.Count == 0 && cols != null)
            pk = cols.Where(c => c.Constraints.OfType<UniqueConstraintDefinition>().Any(u => u.IsPrimaryKey)).Select(c => c.ColumnIdentifier.Value).ToList();
        o["primary_key"] = pk;
        var fks = cs.OfType<ForeignKeyConstraintDefinition>().Select(f => new Dictionary<string, object?>
        {
            ["name"] = f.ConstraintIdentifier?.Value, ["columns"] = f.Columns.Select(c => c.Value).ToList(),
            ["references"] = Util.Name(f.ReferenceTableName), ["ref_columns"] = f.ReferencedTableColumns.Select(c => c.Value).ToList(),
            ["on_delete"] = f.DeleteAction.ToString(),
        }).ToList();
        if (cols != null)
            foreach (var c in cols)
                foreach (var f in c.Constraints.OfType<ForeignKeyConstraintDefinition>())
                    fks.Add(new() { ["name"] = f.ConstraintIdentifier?.Value, ["columns"] = new List<string> { c.ColumnIdentifier.Value },
                        ["references"] = Util.Name(f.ReferenceTableName), ["ref_columns"] = f.ReferencedTableColumns.Select(x => x.Value).ToList(), ["on_delete"] = f.DeleteAction.ToString() });
        o["foreign_keys"] = fks;
        o["unique_constraints"] = cs.OfType<UniqueConstraintDefinition>().Where(u => !u.IsPrimaryKey).Select(u => u.Columns.Select(Util.Col).ToList()).ToList();
        o["checks"] = cs.OfType<CheckConstraintDefinition>().Select(c => Util.Text(c.CheckCondition)).ToList();
    }
}

/// <summary>Walks one statement (or a whole script) and records table reads/writes, calls and SQL Server-specific constructs.</summary>
sealed class Collector : TSqlFragmentVisitor
{
    readonly HashSet<TSqlFragment> targets = new();
    readonly Dictionary<string, string> aliases = new(StringComparer.OrdinalIgnoreCase);
    readonly HashSet<string> ctes = new(StringComparer.OrdinalIgnoreCase);
    readonly SortedSet<string> reads = new(StringComparer.OrdinalIgnoreCase);
    readonly List<(string name, string op)> writes = new();
    readonly SortedSet<string> calls = new(StringComparer.OrdinalIgnoreCase);
    readonly SortedSet<string> functions = new(StringComparer.OrdinalIgnoreCase);
    readonly SortedSet<string> temps = new(StringComparer.OrdinalIgnoreCase);
    readonly SortedDictionary<string, int> constructs = new();
    int resultSets;
    bool returnValue, dynamicSql;

    static readonly Dictionary<string, string> NodeConstructs = new()
    {
        ["DeclareCursorStatement"] = "cursor", ["TryCatchStatement"] = "TRY/CATCH", ["MergeStatement"] = "MERGE",
        ["OutputClause"] = "OUTPUT clause", ["OutputIntoClause"] = "OUTPUT clause", ["PivotedTableReference"] = "PIVOT",
        ["UnpivotedTableReference"] = "UNPIVOT", ["XmlForClause"] = "FOR XML", ["JsonForClause"] = "FOR JSON",
        ["OpenJsonTableReference"] = "OPENJSON", ["OpenXmlTableReference"] = "OPENXML", ["RaiseErrorStatement"] = "RAISERROR",
        ["ThrowStatement"] = "THROW", ["TopRowFilter"] = "TOP", ["WaitForStatement"] = "WAITFOR", ["GoToStatement"] = "GOTO",
        ["SaveTransactionStatement"] = "savepoint", ["BeginTransactionStatement"] = "transactions",
        ["SetIdentityInsertStatement"] = "IDENTITY_INSERT", ["DeclareTableVariableStatement"] = "table variable",
        ["IIfCall"] = "IIF", ["TryConvertCall"] = "TRY_CONVERT", ["TryCastCall"] = "TRY_CAST", ["ParseCall"] = "PARSE",
        ["TryParseCall"] = "PARSE", ["FullTextPredicate"] = "full-text", ["FullTextTableReference"] = "full-text",
        ["CreateFullTextIndexStatement"] = "full-text", ["OpenQueryTableReference"] = "OPENQUERY/OPENROWSET",
        ["OpenRowsetTableReference"] = "OPENQUERY/OPENROWSET", ["InternalOpenRowset"] = "OPENQUERY/OPENROWSET",
        ["ExecuteAsClause"] = "EXECUTE AS", ["ExecuteAsStatement"] = "EXECUTE AS", ["RevertStatement"] = "EXECUTE AS",
        ["CreateSecurityPolicyStatement"] = "row-level security", ["SystemVersioningTableOption"] = "temporal table",
        ["MemoryOptimizedTableOption"] = "memory-optimized", ["CreateColumnStoreIndexStatement"] = "columnstore",
        ["CreatePartitionFunctionStatement"] = "partitioning", ["CreatePartitionSchemeStatement"] = "partitioning",
        ["MethodSpecifier"] = "CLR", ["CreateAssemblyStatement"] = "CLR", ["GraphMatchPredicate"] = "graph MATCH",
        ["UseStatement"] = "USE database", ["SendStatement"] = "Service Broker", ["ReceiveStatement"] = "Service Broker",
        ["BeginDialogStatement"] = "Service Broker", ["EndConversationStatement"] = "Service Broker",
        ["BulkInsertStatement"] = "BULK INSERT", ["CreateSpatialIndexStatement"] = "spatial index",
        ["CreateXmlIndexStatement"] = "XML index", ["XmlDataTypeReference"] = "data type: xml",
        ["CreateEventNotificationStatement"] = "event notification", ["SetCommandStatement"] = "SET options",
        ["WhileStatement"] = "WHILE loop", ["PrintStatement"] = "PRINT", ["CreateTypeTableStatement"] = "table type",
        ["CreateSynonymStatement"] = "synonym", ["CreateSequenceStatement"] = "sequence", ["NextValueForExpression"] = "sequence",
        ["CreateIndexStatement"] = "index", ["CursorDefinition"] = "cursor", ["SetVariableStatement"] = "variables",
        ["ExecuteInsertSource"] = "INSERT EXEC", ["AtTimeZoneCall"] = "AT TIME ZONE", ["OdbcFunctionCall"] = "ODBC escape",
        ["ConvertCall"] = "CONVERT", ["CastCall"] = "CAST", ["CoalesceExpression"] = "COALESCE",
        ["CreateQueueStatement"] = "Service Broker", ["CreateServiceStatement"] = "Service Broker",
        ["CreateContractStatement"] = "Service Broker", ["CreateMessageTypeStatement"] = "Service Broker",
        ["CreateFullTextCatalogStatement"] = "full-text", ["BulkOpenRowset"] = "OPENROWSET BULK",
        ["CreateExternalTableStatement"] = "external table (PolyBase)", ["CreateExternalDataSourceStatement"] = "external table (PolyBase)",
        ["AlterDatabaseSetStatement"] = "database options", ["CreateLoginStatement"] = "logins/users",
        ["CreateUserStatement"] = "logins/users", ["GrantStatement"] = "permissions", ["DenyStatement"] = "permissions",
    };

    static readonly HashSet<string> TsqlFunctions = new(StringComparer.OrdinalIgnoreCase)
    {
        "ISNULL", "GETDATE", "GETUTCDATE", "SYSDATETIME", "SYSUTCDATETIME", "SYSDATETIMEOFFSET", "CURRENT_TIMESTAMP",
        "NEWID", "NEWSEQUENTIALID", "SCOPE_IDENTITY", "IDENT_CURRENT", "DATEADD", "DATEDIFF", "DATEDIFF_BIG", "DATEPART",
        "DATENAME", "EOMONTH", "DATEFROMPARTS", "DATETIMEFROMPARTS", "SWITCHOFFSET", "TODATETIMEOFFSET", "CHARINDEX",
        "PATINDEX", "STUFF", "LEN", "DATALENGTH", "REPLICATE", "SPACE", "QUOTENAME", "FORMAT", "CHOOSE", "STRING_SPLIT",
        "STRING_AGG", "STRING_ESCAPE", "TRANSLATE", "SUSER_SNAME", "SUSER_NAME", "USER_NAME", "HOST_NAME", "APP_NAME",
        "DB_NAME", "DB_ID", "OBJECT_ID", "OBJECT_NAME", "OBJECTPROPERTY", "COL_LENGTH", "ERROR_MESSAGE", "ERROR_NUMBER",
        "ERROR_LINE", "ERROR_PROCEDURE", "ERROR_SEVERITY", "ERROR_STATE", "XACT_STATE", "SESSION_CONTEXT", "CONTEXT_INFO",
        "JSON_VALUE", "JSON_QUERY", "JSON_MODIFY", "ISJSON", "OPENJSON", "CHECKSUM", "BINARY_CHECKSUM", "HASHBYTES",
        "COMPRESS", "DECOMPRESS", "SQUARE", "LOG", "ATN2", "RAND", "SOUNDEX", "DIFFERENCE", "ISNUMERIC", "ISDATE",
        "CONCAT", "CONCAT_WS", "IIF", "TRY_PARSE", "GREATEST", "LEAST", "APPROX_COUNT_DISTINCT", "COUNT_BIG", "GROUPING_ID",
        "ROWCOUNT_BIG", "SERVERPROPERTY", "DATABASEPROPERTYEX", "FILESTREAM", "PATHNAME", "GET_FILESTREAM_TRANSACTION_CONTEXT",
    };

    void Count(string label, int n = 1) => constructs[label] = constructs.GetValueOrDefault(label) + n;

    public override void Visit(TSqlFragment node)
    {
        if (NodeConstructs.TryGetValue(node.GetType().Name, out var label)) Count(label);
        base.Visit(node);
    }

    // ------------------------------------------------------------------ data types and column features
    public override void Visit(SqlDataTypeReference node)
    {
        switch (node.SqlDataTypeOption)
        {
            case SqlDataTypeOption.Money: case SqlDataTypeOption.SmallMoney: case SqlDataTypeOption.SmallDateTime:
            case SqlDataTypeOption.DateTime: case SqlDataTypeOption.DateTimeOffset: case SqlDataTypeOption.UniqueIdentifier:
            case SqlDataTypeOption.Text: case SqlDataTypeOption.NText: case SqlDataTypeOption.Image: case SqlDataTypeOption.Timestamp:
            case SqlDataTypeOption.Rowversion: case SqlDataTypeOption.Sql_Variant: case SqlDataTypeOption.TinyInt: case SqlDataTypeOption.Bit:
                Count("data type: " + node.SqlDataTypeOption.ToString().ToLowerInvariant());
                break;
        }
        if (node.Parameters.Count > 0 && node.Parameters[0] is MaxLiteral) Count("data type: (max)");
    }

    public override void Visit(UserDataTypeReference node)
    {
        var n = node.Name?.BaseIdentifier?.Value?.ToLowerInvariant();
        if (n is "hierarchyid" or "geography" or "geometry" or "sysname") Count("data type: " + n);
    }

    public override void Visit(ColumnDefinition node)
    {
        if (node.IdentityOptions != null) Count("identity column");
        if (node.ComputedColumnExpression != null) Count("computed column");
        if (node.Collation != null) Count("COLLATE");
        if (node.IsRowGuidCol) Count("ROWGUIDCOL");
        if (node.StorageOptions?.IsFileStream == true) Count("FILESTREAM");
    }

    public override void Visit(PredicateSetStatement node)
    {
        // ANSI_NULLS / QUOTED_IDENTIFIER / CONCAT_NULL_YIELDS_NULL etc.; NOCOUNT is harmless
        if ((node.Options & SetOptions.NoCount) != 0 && node.Options == SetOptions.NoCount) return;
        Count(node.IsOn ? "SET options" : "SET option OFF");
    }

    // ------------------------------------------------------------------ table references (reads) and DML targets (writes)
    public override void Visit(NamedTableReference node)
    {
        var name = Util.Name(node.SchemaObject);
        if (node.Alias != null) aliases[node.Alias.Value] = name;
        if (node.TableHints.Count > 0) Count("table hints", node.TableHints.Count);
        if (node.TableHints.Any(h => h.HintKind is TableHintKind.NoLock or TableHintKind.ReadUncommitted)) Count("NOLOCK");
        if (node.SchemaObject?.DatabaseIdentifier != null) Count(node.SchemaObject.ServerIdentifier != null ? "linked server" : "cross-database");
        if (node.TemporalClause != null) Count("temporal query");
        if (targets.Contains(node)) return;
        if (name.StartsWith("#")) { temps.Add(name); Count("temp table"); return; }
        if (name.Equals("inserted", StringComparison.OrdinalIgnoreCase) || name.Equals("deleted", StringComparison.OrdinalIgnoreCase)) { Count("inserted/deleted"); return; }
        reads.Add(name);
    }

    public override void Visit(CommonTableExpression node) { ctes.Add(node.ExpressionName.Value); Count("CTE"); }

    public override void Visit(SchemaObjectFunctionTableReference node)
    {
        var name = Util.Name(node.SchemaObject);
        functions.Add(name);
        if (node.Alias != null) aliases[node.Alias.Value] = name;
    }

    void Target(TableReference? t, string op)
    {
        if (t is NamedTableReference n)
        {
            targets.Add(n);
            var name = Util.Name(n.SchemaObject);
            if (name.StartsWith("#")) { temps.Add(name); return; }
            writes.Add((name, op));
        }
    }

    public override void Visit(InsertSpecification node) => Target(node.Target, "insert");
    public override void Visit(UpdateSpecification node) { Target(node.Target, "update"); if (node.FromClause != null) Count("UPDATE ... FROM"); }
    public override void Visit(DeleteSpecification node) { Target(node.Target, "delete"); if (node.FromClause != null) Count("DELETE ... FROM"); }
    public override void Visit(MergeSpecification node) => Target(node.Target, "merge");
    public override void Visit(TruncateTableStatement node) => writes.Add((Util.Name(node.TableName), "truncate"));

    public override void Visit(SelectStatement node)
    {
        if (node.Into != null) { var n = Util.Name(node.Into); if (n.StartsWith("#")) { temps.Add(n); Count("SELECT INTO #temp"); } else writes.Add((n, "select-into")); return; }
        if (node.QueryExpression is QuerySpecification q && q.SelectElements.Count > 0 && q.SelectElements.All(e => e is SelectSetVariable)) return;
        resultSets++;
    }

    public override void Visit(QualifiedJoin node) { }

    public override void Visit(UnqualifiedJoin node)
    {
        if (node.UnqualifiedJoinType is UnqualifiedJoinType.CrossApply or UnqualifiedJoinType.OuterApply) Count("APPLY");
    }

    // ------------------------------------------------------------------ calls
    public override void Visit(ExecuteSpecification node)
    {
        switch (node.ExecutableEntity)
        {
            case ExecutableProcedureReference p when p.ProcedureReference?.ProcedureReference != null:
                var name = Util.Name(p.ProcedureReference.ProcedureReference.Name);
                calls.Add(name);
                var bare = name.Split('.').Last().ToLowerInvariant();
                if (bare == "sp_executesql") { dynamicSql = true; Count("dynamic SQL"); }
                else if (bare.StartsWith("xp_")) Count("extended procedure (xp_)");
                else if (bare.StartsWith("sp_")) Count("system procedure (sp_)");
                if (p.ProcedureReference.ProcedureReference.Name?.DatabaseIdentifier != null) Count("cross-database");
                break;
            case ExecutableProcedureReference p when p.ProcedureReference?.ProcedureVariable != null:
                dynamicSql = true; Count("dynamic SQL");
                break;
            case ExecutableStringList:
                dynamicSql = true; Count("dynamic SQL");
                break;
        }
    }

    public override void Visit(FunctionCall node)
    {
        var fn = node.FunctionName?.Value ?? "";
        if (node.CallTarget is MultiPartIdentifierCallTarget mp && mp.MultiPartIdentifier.Identifiers.Count >= 2)
        {   // alias.column.Method(): xml / spatial / hierarchyid methods (three-part database.schema.fn() calls are rare)
            Count("method call on column (xml/spatial/hierarchyid)");
            return;
        }
        if (node.CallTarget is MultiPartIdentifierCallTarget mp1)
        {   // schema.fn() or column.Method(): reported as a function; the consumer keeps it only if it names a defined object
            var parts = mp1.MultiPartIdentifier.Identifiers.Select(i => i.Value).Append(fn);
            functions.Add(string.Join(".", parts));
            return;
        }
        if (node.CallTarget != null) { Count("method call on column (xml/spatial/hierarchyid)"); return; }
        if (TsqlFunctions.Contains(fn)) Count("fn: " + fn.ToUpperInvariant());
    }

    public override void Visit(NextValueForExpression node) { if (node.SequenceName != null) functions.Add(Util.Name(node.SequenceName)); }

    public override void Visit(BeginTransactionStatement node) { if (node.Distributed) Count("distributed transaction"); }

    public override void Visit(GlobalVariableExpression node) => Count("global: " + node.Name.ToUpperInvariant());

    public override void Visit(ReturnStatement node) { if (node.Expression != null) returnValue = true; }

    public override void Visit(BinaryExpression node)
    {
        if (node.BinaryExpressionType == BinaryExpressionType.Add && (node.FirstExpression is StringLiteral || node.SecondExpression is StringLiteral)) Count("string concatenation with +");
    }

    public override void Visit(LikePredicate node)
    {
        if (node.SecondExpression is StringLiteral s && s.Value.IndexOf('[') is var a && a >= 0 && s.Value.IndexOf(']', a + 1) > a + 1) Count("LIKE character class");
    }

    public override void Visit(TopRowFilter node)
    {
        if (node.WithTies) Count("TOP WITH TIES");
        if (node.Percent) Count("TOP PERCENT");
    }

    public Dictionary<string, object?> Facts()
    {
        string Resolve(string n) => !n.Contains('.') && aliases.TryGetValue(n, out var real) ? real : n;
        var w = writes.Select(x => (name: Resolve(x.name), x.op)).Distinct()
            .Select(x => new Dictionary<string, string> { ["name"] = x.name, ["op"] = x.op }).ToList();
        var r = reads.Where(x => (!aliases.ContainsKey(x) || x.Contains('.')) && !(ctes.Contains(x) && !x.Contains('.'))).ToList();
        return new()
        {
            ["reads"] = r, ["writes"] = w, ["calls"] = calls.ToList(), ["functions"] = functions.ToList(),
            ["temp_tables"] = temps.ToList(), ["result_sets"] = resultSets, ["return_value"] = returnValue,
            ["dynamic_sql"] = dynamicSql, ["constructs"] = constructs,
        };
    }
}
