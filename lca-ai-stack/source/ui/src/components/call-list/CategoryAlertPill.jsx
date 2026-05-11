import React from 'react';
import { PropTypes } from 'prop-types';

import './CategoryPill.css';
import useSettingsContext from '../../contexts/settings';

// eslint-disable-next-line import/prefer-default-export
export const CategoryAlertPill = (props) => {
  const { settings } = useSettingsContext();
  const regex = settings.CategoryAlertRegex ?? '.*';
  const { alertCount, categories } = props;

  const matchList = [];
  if (categories) {
    categories.forEach((category) => {
      if (category.match(regex)) {
        matchList.push(category);
      }
    });
  }

  if (categories?.length === 0 || alertCount === 0) return null;

  return (
    <span
      className="category-pill-alert-icon"
      title={matchList.join('\n')}
      style={{ cursor: 'pointer' }}
    >
      {alertCount}
    </span>
  );
};

CategoryAlertPill.propTypes = {
  categories: PropTypes.arrayOf(PropTypes.string),
  alertCount: PropTypes.number,
};

CategoryAlertPill.defaultProps = {
  categories: [],
  alertCount: 0,
};
