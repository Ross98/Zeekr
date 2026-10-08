"""Landmark selection and historical road-name rejection."""
import unittest

from zeekr_control.geocoding import short_address


class LandmarkNameTests(unittest.TestCase):
    def test_containing_community_beats_shop_and_distant_mall(self):
        self.assertEqual(short_address(dict(
            aois=[dict(name='春晓小区', distance='0', type='商务住宅;住宅区')],
            pois=[dict(name='便利店', distance='10', type='购物服务;便利店'),
                  dict(name='远处购物中心', distance='400', type='购物服务;商场')])), '春晓小区')

    def test_structured_community_beats_nearest_shop(self):
        self.assertEqual(short_address(dict(
            addressComponent=dict(neighborhood=dict(name='春晓小区2栋')),
            pois=[dict(name='便利店', distance='5', type='购物服务;便利店')])), '春晓小区')

    def test_landmarks_win_only_within_local_distance_window(self):
        for distance, expected in [('90', '购物中心'), ('250', '便利店')]:
            with self.subTest(distance=distance):
                self.assertEqual(short_address(dict(pois=[
                    dict(name='便利店', distance='20', type='购物服务;便利店'),
                    dict(name='购物中心', distance=distance, type='购物服务;商场')])), expected)

    def test_station_beats_shop_and_can_contain_road_name(self):
        self.assertEqual(short_address(dict(pois=[
            dict(name='便利店', distance='20', type='购物服务;便利店'),
            dict(name='人民路站', distance='50', type='交通设施服务;地铁站')])), '人民路站')

    def test_road_descriptions_and_administrative_names_have_no_fallback(self):
        for name in ('测试路', '测试路南0.2km附近', '测试路与另一街交叉口', '浦东新区'):
            with self.subTest(name=name):
                self.assertIsNone(short_address(dict(
                    formatted_address='上海市浦东新区测试路123号',
                    addressComponent=dict(district='浦东新区', streetNumber=dict(street='测试路')),
                    pois=[dict(name=name, distance='10', type='地名地址信息')],
                    aois=[dict(name=name, distance='0', type='地名地址信息')])))

    def test_invalid_distances_and_remote_shops_are_ignored(self):
        pois=[dict(name='测试商铺', distance=d, type='购物服务;专卖店')
              for d in ([], None, True, 'nan', 'inf', '-1', '151')]
        self.assertIsNone(short_address(dict(pois=pois)))
        self.assertEqual(short_address(dict(pois=pois+[
            dict(name='附近商铺', distance='100', type='购物服务;专卖店')])), '附近商铺')

    def test_numbered_names_and_shop_branches_are_preserved(self):
        for name in ('一号公馆', '7号便利店', '便利店(人民路店)'):
            with self.subTest(name=name):
                self.assertEqual(short_address(dict(pois=[dict(name=name, distance='10')])), name)

    def test_shop_branch_is_not_mistaken_for_its_parent_mall(self):
        self.assertEqual(short_address(dict(pois=[
            dict(name='咖啡店(购物中心店)', distance='200', type='餐饮服务;咖啡厅'),
            dict(name='附近商铺', distance='20', type='购物服务;专卖店')])), '附近商铺')
        self.assertEqual(short_address(dict(pois=[
            dict(name='咖啡店(购物中心店)', distance='90'),
            dict(name='人民路站', distance='50')])), '人民路站')

    def test_aoi_numeric_type_codes_are_ranked(self):
        for kind in ('060101', '120302'):
            with self.subTest(kind=kind):
                self.assertEqual(short_address(dict(aois=[
                    dict(name='未来城', distance='200', type=kind)])), '未来城')
        self.assertEqual(short_address(dict(pois=[
            dict(name='附近商铺', distance='20'),
            dict(name='中心站', distance='50', type='150702')])), '中心站')

    def test_shop_type_overrides_landmark_word_in_shop_name(self):
        self.assertEqual(short_address(dict(pois=[
            dict(name='公园咖啡', distance='50', type='餐饮服务;咖啡厅'),
            dict(name='人民路站', distance='70', type='交通设施服务;地铁站')])), '人民路站')

    def test_nearby_aoi_does_not_imply_containment(self):
        self.assertEqual(short_address(dict(
            aois=[dict(name='远处小区', distance='250')],
            pois=[dict(name='附近商铺', distance='20')])), '附近商铺')

    def test_provider_order_does_not_change_equal_distance_result(self):
        pois=[dict(name='乙商铺', distance='10'), dict(name='甲商铺', distance='10')]
        self.assertEqual(short_address(dict(pois=pois)), short_address(dict(pois=pois[::-1])))

    def test_broad_containing_area_does_not_override_specific_mall(self):
        self.assertEqual(short_address(dict(
            aois=[dict(name='江宁大学城',type='140000',distance='0',area='3000000'),
                  dict(name='文鼎广场',type='120203',distance='2.1',area='20000')],
            pois=[dict(name='文鼎金座(文鼎广场店)',type='购物服务;商场;普通商场',distance='54')])), '文鼎广场')

    def test_broad_area_is_last_resort_after_station_or_shop(self):
        for poi in (dict(name='人民路站',type='交通设施服务;地铁站',distance='50'),
                    dict(name='便利店',type='购物服务;便利店',distance='30')):
            with self.subTest(poi=poi):
                self.assertEqual(short_address(dict(
                    aois=[dict(name='江宁大学城',type='140000',distance='0')],pois=[poi])),poi['name'])
        self.assertEqual(short_address(dict(aois=[
            dict(name='江宁大学城',type='140000',distance='0')])), '江宁大学城')

    def test_nested_containing_areas_prefer_smaller_specific_place(self):
        aois=[dict(name='天润城',type='120302',distance='0',area='500000'),
              dict(name='天润城十三街区',type='120302',distance='0',area='30000')]
        self.assertEqual(short_address(dict(aois=aois)), '天润城十三街区')
        self.assertEqual(short_address(dict(aois=aois[::-1])), '天润城十三街区')

    def test_invalid_area_size_does_not_break_selection(self):
        for area in (None, [], True, 'nan', '-1'):
            with self.subTest(area=area):
                self.assertEqual(short_address(dict(aois=[
                    dict(name='春晓小区',distance='0',type='120302',area=area)])), '春晓小区')

    def test_named_subareas_are_not_mistaken_for_administrative_districts(self):
        for name in ('天润城十三街区', '科创城D区', '解溪佳苑一区', '科技园南区'):
            with self.subTest(name=name):
                self.assertEqual(short_address(dict(aois=[
                    dict(name=name,type='120302',distance='0',area='10000')])), name)

    def test_containing_secondary_venue_does_not_hide_nearby_mall(self):
        self.assertEqual(short_address(dict(aois=[
            dict(name='乐动力江宁数字体育中心',type='080101',distance='0',area='226498'),
            dict(name='江宁大学城',type='140000',distance='0',area='19200206'),
            dict(name='文鼎广场',type='120203',distance='36.3',area='56110')])), '文鼎广场')

    def test_neighbouring_communities_with_similar_evidence_are_unresolved(self):
        aois=[dict(name='津桥华府',type='120302',distance='9.8'),
              dict(name='梧桐语',type='120302',distance='13.9'),
              dict(name='珑熹台',type='120302',distance='46.2')]
        self.assertIsNone(short_address(dict(aois=aois)))
        self.assertIsNone(short_address(dict(aois=aois[::-1])))

    def test_apartment_and_industrial_park_boundary_is_ambiguous(self):
        self.assertIsNone(short_address(dict(aois=[
            dict(name='菁英公寓',type='120302',distance='11.7'),
            dict(name='菁英公寓B区',type='120302',distance='18.9'),
            dict(name='南京软件谷科创城',type='120100',distance='21.1'),
            dict(name='南京软件谷科创城D区',type='120100',distance='31')],
            pois=[dict(name='菁英公寓',type='商务住宅;住宅区',distance='147')])))

    def test_confirmed_parent_is_retained_between_neighbouring_subareas(self):
        self.assertEqual(short_address(dict(aois=[
            dict(name='天润城',type='120302',distance='0',area='1772245'),
            dict(name='苏宁天润城十四街区',type='120302',distance='9.1',area='128823'),
            dict(name='天润城十三街区',type='120302',distance='26.3',area='64307')])), '天润城')

    def test_different_containing_places_are_not_resolved_by_area_size_alone(self):
        self.assertIsNone(short_address(dict(aois=[
            dict(name='春晓小区',type='120302',distance='0',area='10000'),
            dict(name='晨光小区',type='120302',distance='0',area='20000')])))

    def test_unique_clear_winner_and_duplicate_poi_evidence_are_preserved(self):
        self.assertEqual(short_address(dict(aois=[
            dict(name='春晓小区',type='120302',distance='5'),
            dict(name='晨光小区',type='120302',distance='90')],
            pois=[dict(name='春晓小区',type='商务住宅;住宅区',distance='80')])), '春晓小区')

    def test_broad_area_cannot_mask_conflict_between_specific_places(self):
        self.assertIsNone(short_address(dict(aois=[
            dict(name='江宁大学城',type='140000',distance='0'),
            dict(name='春晓小区',type='120302',distance='10'),
            dict(name='晨光小区',type='120302',distance='15')])))

    def test_clearly_closer_aoi_is_not_rejected_for_nearby_neighbour(self):
        for first,second in ((2.9,24.3),(.6,12.4),(0,8)):
            with self.subTest(distances=(first,second)):
                self.assertEqual(short_address(dict(aois=[
                    dict(name='春晓小区',type='120302',distance=str(first)),
                    dict(name='晨光小区',type='120302',distance=str(second))])), '春晓小区')

    def test_similar_names_do_not_prove_a_parent_relationship(self):
        self.assertIsNone(short_address(dict(aois=[
            dict(name='春晓小区',type='120302',distance='10'),
            dict(name='新春晓小区',type='120302',distance='12')])))

    def test_named_parking_facility_is_not_a_conflicting_peer_of_its_mall(self):
        for first,second in ((2.1,4),(0,0),(36.3,37.8)):
            with self.subTest(distances=(first,second)):
                self.assertEqual(short_address(dict(aois=[
                    dict(name='文鼎广场',type='120203',distance=str(first),area='56110'),
                    dict(name='文鼎广场停车场',type='150904',distance=str(second),area='9672')])), '文鼎广场')

    def test_conflicting_contained_subareas_use_only_returned_common_parent(self):
        self.assertEqual(short_address(dict(aois=[
            dict(name='天润城',type='120302',distance='0',area='500000'),
            dict(name='天润城十三街区',type='120302',distance='0',area='30000'),
            dict(name='天润城十四街区',type='120302',distance='0',area='20000')])), '天润城')
