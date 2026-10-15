"""
将 ORM API 或 SQL 获取的数据，转换为前端报表的数据结构
"""
import logging

_logger = logging.getLogger(__name__)


class DataConvertFieldsError(Exception):
    pass


class DataPoint:
    def __init__(self, name, value, filter_domain, category):
        self.name = name
        self.value = value
        self.filter_domain = filter_domain
        self.category = category

    def to_dict(self):
        return {
            'name': self.name,
            'value': self.value,
            'filter_domain': self.filter_domain,
            'category': self.category
        }


class SqlDataConvert:
    def __init__(self, env, model, fields):
        """

        :param model:
        :param fields:
        """
        self.env = env
        self.model = model
        self.fields = fields

        # 数据
        self.datas: list[DataPoint] = []
        self.x_field = None

    def convert(self, data):
        # data -> list[DataPoint]
        self._parse_sql(data)

        # DataPoint.name 的 many2one转换
        x_axis = [p.name for p in self.datas]
        x_name_map = self._get_name_map(self.x_field, x_axis)
        if x_name_map is not None:
            for p in self.datas:
                p.name = x_name_map.get(p.name, 'NULL')

        # DataPoint.category 的 many2one转换
        categories = list({p.category for p in self.datas})
        c_name_map = self._get_name_map(self.c_field, list(categories))
        if c_name_map is not None:
            for p in self.datas:
                p.category = c_name_map.get(p.category, 'NULL')

        # list[DataPoint] -> list[dict]
        return [p.to_dict() for p in self.datas]

    def set_x_field(self, field):
        """
        设置完x轴字段后，`__count`被认为是y轴，剩下的字段被认为数据源分类（比如折线图中的多个线条）
        若不设置x轴，则自动将第一个字段设置为x轴
        :param field:
        :return:
        """
        self.x_field = field

    def _parse_sql(self, data):
        """
        many2one字段在这里仍是id

        :param data:
        :return: list[DataUnit]
        """
        if '__count' not in self.fields:
            raise DataConvertFieldsError('not fount `__count` field')

        # 设置x轴、category字段
        if self.x_field is None:
            self.x_field = next((f for f in self.fields if f != '__count'), None)  # 寻找第一个不是`__count`的字段
            _logger.info("The x-axis field is not set, default selection is %s", self.x_field)

        self.c_field = next((f for f in self.fields if f not in {'__count', self.x_field}), None)

        # 生成datas数组
        xf_index = self.fields.index(self.x_field)
        cf_index = self.fields.index(self.c_field) if self.c_field else None
        yf_index = self.fields.index('__count')
        for du in data:
            if len(du) != len(self.fields):
                raise DataConvertFieldsError(
                    'The number of fields set does not match the number of data provided, fields: %s, data: %s' %
                    self.fields, du
                )

            filter_domain = [(self.x_field, '=', du[xf_index])]
            if cf_index:
                filter_domain.append((self.c_field, '=', du[cf_index]))

            self.datas.append(DataPoint(
                name=du[xf_index],
                value=du[yf_index],
                filter_domain=filter_domain,
                category=du[cf_index] if cf_index else None
            ))

    def _get_name_map(self, field, ids):
        if not field:
            return None

        model_obj = self.env[self.model]
        if model_obj._fields.get(field).type != 'many2one':
            return None

        co_model_obj = getattr(model_obj, field)
        recs = co_model_obj.browse(ids)
        return {r['id']: r['name'] for r in recs.read(['id', 'name'])}
